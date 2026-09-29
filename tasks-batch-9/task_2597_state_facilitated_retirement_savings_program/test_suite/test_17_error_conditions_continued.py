"""
Refusals raised deeper in the money and enforcement workflows.

A movement of retirement savings must stay inside one person's own accounts and
inside the balance that account actually holds; a sixty-day rollover that misses
its settlement date fails as a lapsed window rather than as a bad state, and once
it has been compensated the very same call fails as a bad state instead; a
correction case has to be elected before it can be executed and cannot be elected
after the following spring's filing date; an assessment cannot be escalated to an
outside agency before it has been affirmed; a qualified plan whose three-year
coverage has already elapsed cannot support a present exemption; and a closure
cannot be finalised over money still sitting in the account.

Each refusal is paired with the state it must leave untouched, and — where the
programme allows the blocking condition to be lifted — with the identical request
being accepted afterwards.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ERR_ACCOUNT_OWNER_MISMATCH,
    ERR_CORRECTION_DEADLINE_PASSED,
    ERR_EXCESS_CASE_STATE_INVALID,
    ERR_EXEMPTION_WINDOW_CLOSED,
    ERR_INSUFFICIENT_ACCOUNT_BALANCE,
    ERR_PENALTY_STATE_INVALID,
    ERR_RESIDUAL_BALANCE_PRESENT,
    ERR_ROLLOVER_WINDOW_EXPIRED,
    ERR_TRANSFER_STATE_INVALID,
    OFFICER_A,
    OFFICER_B,
    OFFICER_B_USER_ID,
    PARTICIPANT_ANA,
    PROGRAM_YEAR_2027,
    RECORDKEEPER,
    account_for_participant,
    activate_savers,
    assert_amounts,
    assert_fields,
    assert_nulls,
    assert_total_count,
    assess_penalty,
    build_active_saver_environment,
    build_employer_environment,
    build_excess_case_environment,
    build_notified_saver,
    create_enrollment,
    create_participant,
    create_program_year,
    dispose_penalty,
    fund_account_by_remittance,
    make_employer_headers,
    make_participant_headers,
    read_account,
    read_employer,
    read_excess_case,
    read_penalty,
    read_transfer,
    request_closure,
    request_transfer,
    return_transfer,
    set_clock,
)

# One pay cycle whose whole withholding lands in the saver's account: 8 000 000
# cents of gross wages at the programme default of 500 basis points.
CYCLE_GROSS_CENTS = 8000000
CYCLE_DEDUCTED_CENTS = 400000


def _funded_saver(api, posting_clock="2026-02-05T00:00:00Z"):
    """
    A live saver whose account holds exactly one posted payroll deduction, so its
    balance is entirely contribution basis and its posture is unrestricted.
    """
    env = build_active_saver_environment(api)
    env.update(fund_account_by_remittance(
        api, env, "2026-01-01", "2026-01-31", "2026-02-05",
        CYCLE_GROSS_CENTS, CYCLE_DEDUCTED_CENTS, posting_clock,
        posting_reference="PR-2026-0205"))
    return env


def _two_savers_with_only_one_funded(api):
    """
    Two live savers at the same employer, where only the first one's account has
    received a posted payroll deduction; the second account is open but empty.
    """
    env = build_employer_environment(api)
    build_notified_saver(api, env)
    other = create_participant(api, PARTICIPANT_ANA)
    create_enrollment(api, env["employer_id"], other["id"])
    activate_savers(api, env)
    env["other_participant_id"] = other["id"]
    env["other_account_id"] = account_for_participant(api, other["id"])["id"]
    env.update(fund_account_by_remittance(
        api, env, "2026-01-01", "2026-01-31", "2026-02-05",
        CYCLE_GROSS_CENTS, CYCLE_DEDUCTED_CENTS, "2026-02-05T00:00:00Z",
        posting_reference="PR-2026-0205"))
    return env


def _transfer_payload(participant_id, source_account_id, amount_cents):
    """A well-formed request to move money out to an outside institution."""
    return {
        "participant_id": participant_id,
        "source_account_id": source_account_id,
        "destination_type": "EXTERNAL_IRA",
        "transfer_kind": "DIRECT_ROLLOVER",
        "external_institution_name": "Harborline Trust Company",
        "amount_cents": amount_cents,
    }


def test_a_transfer_naming_another_savers_account_as_its_source_is_refused(api):
    """
    A request that names one saver as the owner but somebody else's account as the
    account to debit is refused as an ownership mismatch, and neither account moves.

    "Portability moves money within one person's own savings and is never a
    transfer between two people: a source account that does not belong to the
    named participant, a destination equal to the source, a destination belonging
    to a different participant, or a destination account that is not open, is
    refused with `ERR_ACCOUNT_OWNER_MISMATCH`."

    Design: Corner/errors/portability_transfer_rejects_a_foreign_account_and_an_overdraw
    """
    env = _two_savers_with_only_one_funded(api)

    response = api.create_portability_transfer(
        _transfer_payload(env["participant_id"], env["other_account_id"], 100000),
        ADMIN)

    validate_error(response, ERR_ACCOUNT_OWNER_MISMATCH)
    assert_amounts(read_account(api, env["other_account_id"]), {
        "balance_cents": 0,
        "contribution_basis_cents": 0,
    }, label="the account that was named by mistake")
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": CYCLE_DEDUCTED_CENTS,
        "contribution_basis_cents": CYCLE_DEDUCTED_CENTS,
    }, label="the funded account of the named owner")
    assert_total_count(api.list_portability_transfers(ADMIN), 0,
                       label="transfers after the ownership refusal")


def test_a_transfer_larger_than_the_balance_is_refused_and_debits_nothing(api):
    """
    A saver may only move out what the account actually holds: a gross amount above
    the balance is refused as insufficient funds, and the account is left whole,
    unrestricted and with no in-flight leg anywhere.

    "The request is refused with `ERR_ACCOUNT_CLOSED` when the source account is
    `CLOSED`, with `ERR_ACCOUNT_RESTRICTED` when its posture is `RESTRICTED` or
    `LOCKED`, and with `ERR_INSUFFICIENT_ACCOUNT_BALANCE` when the gross
    `amount_cents` exceeds the source `balance_cents`."

    Design: Corner/errors/portability_transfer_rejects_a_foreign_account_and_an_overdraw
    """
    env = _two_savers_with_only_one_funded(api)
    assert read_account(api, env["account_id"])["balance_cents"] == 400000

    response = api.create_portability_transfer(
        _transfer_payload(env["participant_id"], env["account_id"], 500000),
        make_participant_headers(env["participant_id"]))

    validate_error(response, ERR_INSUFFICIENT_ACCOUNT_BALANCE)
    account = read_account(api, env["account_id"])
    assert_amounts(account, {
        "balance_cents": 400000,
        "contribution_basis_cents": 400000,
    }, label="account after the oversized request")
    assert account["posture"] == "UNRESTRICTED"
    assert_total_count(api.list_portability_transfers(ADMIN), 0,
                       label="transfers after the balance refusal")


def _indirect_rollover_in_flight(api):
    """
    A funded account with a sixty-day indirect rollover of 100000 cents requested
    on 10 March 2026, so its settlement date falls on 9 May 2026.
    """
    env = _funded_saver(api)
    set_clock(api, "2026-03-10T00:00:00Z")
    transfer = request_transfer(
        api, env["participant_id"], env["account_id"], 100000,
        transfer_kind="INDIRECT_60_DAY",
        external_institution_name="Harborline Trust Company")
    env["transfer"] = transfer
    env["transfer_id"] = transfer["id"]
    return env


def test_an_indirect_rollover_settled_after_its_sixty_days_is_refused(api):
    """
    The recordkeeper reports a settlement date one day past the sixty-day limit and
    the settlement is refused as a lapsed rollover window; the transfer keeps its
    in-flight leg and its original settlement date.

    "For an `INDIRECT_60_DAY` transfer, `settled_on` must be on or before
    `settle_by_date`, and a later date is refused with
    `ERR_ROLLOVER_WINDOW_EXPIRED`."

    Design: Corner/errors/rollover_settlement_past_the_deadline_and_after_return_are_both_rejected
    """
    env = _indirect_rollover_in_flight(api)
    assert env["transfer"]["settle_by_date"] == "2026-05-09"
    set_clock(api, "2026-05-10T00:00:00Z")

    response = api.settle_portability_transfer(
        env["transfer_id"],
        {"settled_on": "2026-05-10", "settlement_reference": "RK-LATE-0001"},
        RECORDKEEPER)

    validate_error(response, ERR_ROLLOVER_WINDOW_EXPIRED)
    transfer = read_transfer(api, env["transfer_id"])
    assert_fields(transfer, {
        "status": "REQUESTED",
        "settle_by_date": "2026-05-09",
        "is_taxable_distribution": False,
    }, label="transfer after the late settlement attempt")
    assert_nulls(transfer, ["settled_on", "settlement_reference"],
                 label="transfer after the late settlement attempt")
    assert_amounts(transfer, {"in_transit_cents": 100000}, label="transfer")


def test_settling_a_returned_rollover_is_refused_on_its_state_not_its_window(api):
    """
    Once the lapsed transfer has been returned instead, the money is back in the
    account and the very same settlement call is refused for the transfer's
    terminal state rather than for the window it also misses.

    "Three endings are possible, and each is available only while the transfer is
    still `REQUESTED`; attempting to settle or return anything else is refused
    with `ERR_TRANSFER_STATE_INVALID`."

    Design: Corner/errors/rollover_settlement_past_the_deadline_and_after_return_are_both_rejected
    """
    env = _indirect_rollover_in_flight(api)
    set_clock(api, "2026-05-10T00:00:00Z")
    validate_error(
        api.settle_portability_transfer(
            env["transfer_id"],
            {"settled_on": "2026-05-10", "settlement_reference": "RK-LATE-0001"},
            RECORDKEEPER),
        ERR_ROLLOVER_WINDOW_EXPIRED)

    returned = return_transfer(
        api, env["transfer_id"], "Receiving institution never opened the account")

    assert returned["status"] == "RETURNED"
    assert_amounts(returned, {"in_transit_cents": 0}, label="returned transfer")
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": CYCLE_DEDUCTED_CENTS,
        "contribution_basis_cents": CYCLE_DEDUCTED_CENTS,
    }, label="account after the compensating return")

    response = api.settle_portability_transfer(
        env["transfer_id"],
        {"settled_on": "2026-05-09", "settlement_reference": "RK-LATE-0002"},
        RECORDKEEPER)

    validate_error(response, ERR_TRANSFER_STATE_INVALID)
    assert_nulls(read_transfer(api, env["transfer_id"]),
                 ["settled_on", "settlement_reference"],
                 label="returned transfer after the second settlement attempt")


def _detected_excess_case_with_next_year_configured(api):
    """
    Two posted batches have carried the saver past the annual ceiling, leaving one
    unresolved case whose correction deadline falls on the ordinary filing date of
    the following spring — a year whose dials are configured too, so nothing about
    the deadline turns on missing configuration.
    """
    env = build_excess_case_environment(api)
    create_program_year(api, PROGRAM_YEAR_2027)
    return env


def test_executing_a_correction_before_a_method_is_elected_is_refused(api):
    """
    The recordkeeper cannot execute a correction the saver has not yet chosen: a
    completion against a freshly detected case is refused on its state, and the
    case keeps every unresolved field null.

    "The case must be in `METHOD_ELECTED` and the clock date must still be on or
    before `deadline_date`."

    Design: Corner/errors/excess_completion_before_election_and_election_after_deadline_are_rejected
    """
    env = _detected_excess_case_with_next_year_configured(api)
    assert env["excess_case"]["status"] == "DETECTED"

    response = api.complete_excess_case(
        env["excess_case_id"], {"settlement_reference": "RK-EXC-0001"},
        RECORDKEEPER)

    validate_error(response, ERR_EXCESS_CASE_STATE_INVALID)
    case = read_excess_case(api, env["excess_case_id"])
    assert case["status"] == "DETECTED"
    assert_nulls(case, ["correction_method", "settlement_reference",
                        "completed_at", "closing_fmv_cents"],
                 label="case after the premature completion")


def test_electing_a_correction_method_after_the_filing_deadline_is_refused(api):
    """
    The saver's own election is refused once the following spring's filing date has
    gone by; the case stays detected with no method recorded and the account stays
    restricted, while the uncorrected total still reads zero because nothing has
    expired yet.

    "Either the owning `Participant` or a `ProgramAdministrator` may elect a
    `correction_method` of `REFUND_TO_PARTICIPANT`,
    `RECHARACTERIZE_TO_TRADITIONAL` or `CARRY_FORWARD` while the case is in
    `DETECTED` and the clock date is on or before `deadline_date`; a later attempt
    is refused with `ERR_CORRECTION_DEADLINE_PASSED`, and an attempt against a
    case in any status other than `DETECTED` is refused with
    `ERR_EXCESS_CASE_STATE_INVALID`."

    Design: Corner/errors/excess_completion_before_election_and_election_after_deadline_are_rejected
    """
    env = _detected_excess_case_with_next_year_configured(api)
    assert env["excess_case"]["deadline_date"] == "2027-04-15"
    set_clock(api, "2027-04-16T00:00:00Z")

    response = api.elect_correction_method(
        env["excess_case_id"], {"correction_method": "REFUND_TO_PARTICIPANT"},
        make_participant_headers(env["participant_id"]))

    validate_error(response, ERR_CORRECTION_DEADLINE_PASSED)
    case = read_excess_case(api, env["excess_case_id"])
    assert_fields(case, {
        "status": "DETECTED",
        "deadline_date": "2027-04-15",
    }, label="case after the late election")
    assert case["correction_method"] is None
    account = read_account(api, env["account_id"])
    assert account["posture"] == "RESTRICTED"
    assert_amounts(account, {"uncorrected_excess_cents": 0},
                   label="account whose case has not expired")


def _assessed_penalty_inside_its_cure_period(api):
    """
    A registered employer noticed for a remittance failure on 5 January 2026, with
    the statutory thirty-day cure period still running.
    """
    env = build_employer_environment(api)
    penalty = assess_penalty(api, env["employer_id"], "FAILURE_TO_REMIT",
                             "2026-01-05", headers=OFFICER_A)
    env["penalty"] = penalty
    env["penalty_id"] = penalty["id"]
    return env


def test_referring_an_assessment_still_inside_its_cure_period_is_refused(api):
    """
    An employer cannot be escalated to an outside agency before its assessment has
    been affirmed, and while the cure period runs affirmation is not yet possible;
    the refusal leaves no referral behind and the employer merely penalised.

    "Referral is the programme's escalation to an outside authority, and only a
    `ComplianceOfficer` may raise one, and only against an assessment in status
    `AFFIRMED`; an assessment still inside its cure period cannot be referred,
    because it cannot yet be affirmed, and an attempt is refused with
    `ERR_PENALTY_STATE_INVALID`."

    Design: Corner/errors/enforcement_referral_on_an_unaffirmed_penalty_is_rejected
    """
    env = _assessed_penalty_inside_its_cure_period(api)
    assert_fields(env["penalty"], {
        "status": "ASSESSED",
        "cure_deadline": "2026-02-04",
    }, label="assessment inside its cure period")

    response = api.create_enforcement_referral(
        env["penalty_id"],
        {"agency": "STATE_LABOR_COMMISSIONER",
         "referral_basis": "Sustained failure to remit withheld contributions"},
        OFFICER_B)

    validate_error(response, ERR_PENALTY_STATE_INVALID)
    assert read_penalty(api, env["penalty_id"])["status"] == "ASSESSED"
    assert_total_count(
        api.list_enforcement_referrals(env["penalty_id"], OFFICER_B), 0,
        label="referrals of an unaffirmed assessment")
    assert read_employer(api, env["employer_id"])["compliance_status"] == (
        "PENALIZED")


def test_the_same_referral_is_accepted_once_the_assessment_is_affirmed(api):
    """
    After the cure period lapses a second officer affirms the assessment, and the
    identical referral is then accepted: it opens against the affirmed assessment,
    names the officer who raised it and freezes the employer's identifier as sent.

    "It is created in status `OPEN`, with `referred_at` stamped from the clock,
    `referred_by_user_id` set to the raising officer's `X-User-ID`, and
    `employer_ein_snapshot` denormalised from the employer's `ein` at that instant
    and never re-derived afterwards, so the referral remains an accurate record of
    what was sent even if the employer later restates its identifiers."

    Design: Corner/errors/enforcement_referral_on_an_unaffirmed_penalty_is_rejected
    """
    env = _assessed_penalty_inside_its_cure_period(api)
    referral_payload = {
        "agency": "STATE_LABOR_COMMISSIONER",
        "referral_basis": "Sustained failure to remit withheld contributions",
    }
    validate_error(
        api.create_enforcement_referral(
            env["penalty_id"], referral_payload, OFFICER_B),
        ERR_PENALTY_STATE_INVALID)

    set_clock(api, "2026-02-05T00:00:00Z")
    affirmed = dispose_penalty(api, env["penalty_id"], "AFFIRM",
                               headers=OFFICER_B)
    assert affirmed["status"] == "AFFIRMED"

    referral = validate_success(
        api.create_enforcement_referral(
            env["penalty_id"], referral_payload, OFFICER_B),
        expected_status=201)

    assert_fields(referral, {
        "penalty_id": env["penalty_id"],
        "agency": "STATE_LABOR_COMMISSIONER",
        "status": "OPEN",
        "referred_by_user_id": OFFICER_B_USER_ID,
        "employer_ein_snapshot": read_employer(api, env["employer_id"])["ein"],
    }, label="referral raised against an affirmed assessment")
    assert referral["withdrawn_reason"] is None
    assert read_employer(api, env["employer_id"])["compliance_status"] == (
        "REFERRED")


def _exemption_filing(plan_effective_date):
    """A complete qualified-plan certification for a controlled-group sponsor."""
    return {
        "qualified_plan_type": "401K",
        "plan_sponsor_ein": "99-1112223",
        "plan_effective_date": plan_effective_date,
        "attestation_accepted": True,
    }


def test_a_certification_whose_three_year_window_has_elapsed_is_refused(api):
    """
    A plan that took effect in 2022 has already run out its three years by the time
    the employer files in 2026, so the certification is refused as a closed window
    and nothing is filed against the employer.

    "Separately, a certification whose derived `coverage_period_end` is on or
    before the current clock date is refused with `ERR_EXEMPTION_WINDOW_CLOSED` —
    a plan whose three-year window has already elapsed cannot support a present
    exemption, and the employer must re-certify with a current effective date."

    Design: Corner/errors/exemption_filing_with_a_lapsed_coverage_window_is_rejected
    """
    env = build_employer_environment(api)

    response = api.create_exemption_certification(
        env["employer_id"], _exemption_filing("2022-01-01"),
        make_employer_headers(env["employer_id"]))

    validate_error(response, ERR_EXEMPTION_WINDOW_CLOSED)
    assert_total_count(
        api.list_employer_exemption_certifications(env["employer_id"], ADMIN), 0,
        label="certifications after the lapsed-window refusal")
    assert read_employer(api, env["employer_id"])["registration_status"] == (
        "REGISTERED")


def test_a_current_effective_date_is_accepted_and_opens_a_live_window(api):
    """
    Re-certifying with an effective date whose three years still cover the present
    clock is accepted, and the derived interval runs from that date to exactly
    three years later as its exclusive upper bound.

    "`coverage_period_start` equals `plan_effective_date` and is the inclusive
    lower bound; `coverage_period_end` equals `plan_effective_date` plus three
    years and is the **exclusive** upper bound."

    Design: Corner/errors/exemption_filing_with_a_lapsed_coverage_window_is_rejected
    """
    env = build_employer_environment(api)
    validate_error(
        api.create_exemption_certification(
            env["employer_id"], _exemption_filing("2022-01-01"),
            make_employer_headers(env["employer_id"])),
        ERR_EXEMPTION_WINDOW_CLOSED)

    response = api.create_exemption_certification(
        env["employer_id"], _exemption_filing("2024-06-01"),
        make_employer_headers(env["employer_id"]))

    certification = validate_success(response, expected_status=201)
    assert_fields(certification, {
        "employer_id": env["employer_id"],
        "qualified_plan_type": "401K",
        "coverage_period_start": "2024-06-01",
        "coverage_period_end": "2027-06-01",
        "status": "SUBMITTED",
    }, label="certification filed with a current effective date")
    assert read_employer(api, env["employer_id"])["registration_status"] == (
        "REGISTERED")


def test_closure_cannot_be_finalised_while_the_account_still_holds_money(api):
    """
    A pending closure over a funded account cannot be completed: the residual
    balance has to be drained through an ordinary distribution first, so the
    completion is refused and the account stays pending, locked and fully funded.

    "The account must be in `CLOSURE_PENDING`, else `ERR_CLOSURE_STATE_INVALID`;
    its `balance_cents` must be exactly zero, else `ERR_RESIDUAL_BALANCE_PRESENT`;
    and no excess-contribution case of the account may remain in `DETECTED` or
    `METHOD_ELECTED`, since an unresolved correction cannot be executed against a
    closed account."

    Design: Corner/errors/closure_completion_with_a_residual_balance_is_rejected
    """
    env = _funded_saver(api)
    set_clock(api, "2026-02-20T00:00:00Z")
    pending = request_closure(api, env["account_id"], env["participant_id"])
    assert_fields(pending, {
        "account_status": "CLOSURE_PENDING",
        "posture": "LOCKED",
    }, label="account after the closure request")

    response = api.complete_account_closure(env["account_id"], RECORDKEEPER)

    validate_error(response, ERR_RESIDUAL_BALANCE_PRESENT)
    account = read_account(api, env["account_id"])
    assert_fields(account, {
        "account_status": "CLOSURE_PENDING",
        "posture": "LOCKED",
        "closure_reason": "PARTICIPANT_REQUEST",
        "residual_disposition": "CASH_DISTRIBUTION",
    }, label="account after the refused completion")
    assert_amounts(account, {"balance_cents": CYCLE_DEDUCTED_CENTS},
                   label="account that still holds its contributions")
    assert account["closed_at"] is None


def test_the_same_completion_is_accepted_on_an_account_holding_nothing(api):
    """
    An account that never received a deduction has nothing to strand, so the
    identical completion call is accepted: the account closes, the closing instant
    is stamped and its standing fund election is stood down.

    "On success the account moves `CLOSURE_PENDING → CLOSED`, `closed_at` is
    stamped from the logical clock, the account's currently `ACTIVE` investment
    election becomes `SUPERSEDED` and `active_election_id` is cleared to null, and
    the account's `version` increments."

    Design: Corner/errors/closure_completion_with_a_residual_balance_is_rejected
    """
    env = build_active_saver_environment(api)
    assert read_account(api, env["account_id"])["balance_cents"] == 0
    request_closure(api, env["account_id"], env["participant_id"])

    response = api.complete_account_closure(env["account_id"], RECORDKEEPER)

    closed = validate_success(response)
    assert_fields(closed, {
        "account_status": "CLOSED",
        "posture": "LOCKED",
    }, label="account closed with no residual balance")
    assert closed["closed_at"] is not None
    assert closed["active_election_id"] is None
