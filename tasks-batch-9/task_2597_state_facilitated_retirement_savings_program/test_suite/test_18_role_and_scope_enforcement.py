"""
Who may act, and on whose rows.

The programme separates five roles that are peers rather than a hierarchy, and
it separates two of them further by identity: an employer and a saver each act
under their own row identifier, so a request that clears the role gate can still
fail the ownership gate. Three refusals are deliberately distinct — the wrong
role is told `ERR_UNAUTHORIZED`, the right role reaching into someone else's
subtree is told `ERR_FORBIDDEN_SCOPE`, and an employer reaching for a saver's
own decision is told `ERR_FIDUCIARY_BOUNDARY_VIOLATION` so the attempt leaves an
auditable trail. Segregation of duties inside a single role is enforced on the
recorded actor identifiers rather than on the role name.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN,
    CLOCK_2026_02_01,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_FIDUCIARY_BOUNDARY_VIOLATION,
    ERR_FORBIDDEN_SCOPE,
    ERR_SELF_DISPOSITION_FORBIDDEN,
    ERR_UNAUTHORIZED,
    OFFICER_A,
    OFFICER_A_USER_ID,
    OFFICER_B,
    OFFICER_B_USER_ID,
    PARTICIPANT_ROSA,
    PARTICIPANT_TOMAS,
    RECORDKEEPER,
    account_for_participant,
    assert_fields,
    assert_total_count,
    build_active_saver_environment,
    build_employer_environment,
    create_enrollment,
    create_participant,
    create_remittance,
    file_exemption,
    make_employer_headers,
    make_participant_headers,
    read_account,
    read_enrollment,
    read_exemption,
    read_participant,
    read_penalty,
    read_remittance,
    run_auto_enrollment,
    set_clock,
)


def _two_savers_with_their_own_accounts(api):
    """
    One registered employer and two savers, each activated by the auto-enrolment
    batch so each holds an account of their own. Two accounts owned by two
    different people is what an ownership-scope refusal needs: the caller reaches
    for an account that genuinely exists and genuinely belongs to somebody else.
    """
    env = build_employer_environment(api)
    savers = []
    for profile in (PARTICIPANT_ROSA, PARTICIPANT_TOMAS):
        saver = create_participant(api, profile)
        enrollment = create_enrollment(api, env["employer_id"], saver["id"])
        savers.append({"participant": saver, "enrollment": enrollment})
    set_clock(api, CLOCK_2026_02_01)
    run_auto_enrollment(api)
    for saver in savers:
        saver["account"] = account_for_participant(api, saver["participant"]["id"])
    env["savers"] = savers
    return env


def test_employer_reaching_for_a_savers_rate_or_opt_out_hits_the_boundary(api):
    """
    The employer is on both of these routes and owns the enrolment it addresses,
    so it clears the role gate and the ownership gate and is stopped only by the
    ministerial boundary. Neither attempt leaves a mark, and the saver then makes
    the very election the employer was refused.

    "A rate election and an opt-out *do* admit the `Employer` role onto the
    route, precisely so that an employer's attempt is refused by the named,
    auditable `ERR_FIDUCIARY_BOUNDARY_VIOLATION` (HTTP 403) rather than by an
    indistinguishable role check — the programme wants a record that an employer
    reached for a saver's decision."

    Design: Corner/rbac/employer_rate_election_and_opt_out_are_rejected_at_the_fiduciary_boundary
    """
    env = build_active_saver_environment(api)
    employer_headers = make_employer_headers(env["employer_id"])

    rate_attempt = api.elect_contribution_rate(
        env["enrollment_id"], {"contribution_rate_bp": 300}, employer_headers)
    opt_out_attempt = api.opt_out_enrollment(
        env["enrollment_id"], {"opt_out_reason_code": "AFFORDABILITY"},
        employer_headers)

    validate_error(rate_attempt, ERR_FIDUCIARY_BOUNDARY_VIOLATION)
    validate_error(opt_out_attempt, ERR_FIDUCIARY_BOUNDARY_VIOLATION)
    untouched = read_enrollment(api, env["enrollment_id"])
    assert_fields(untouched, {
        "contribution_rate_bp": 500,
        "rate_source": "DEFAULT",
        "enrollment_status": "ACTIVE",
        "opted_out_at": None,
    }, label="enrolment after both employer attempts")

    elected = validate_success(api.elect_contribution_rate(
        env["enrollment_id"], {"contribution_rate_bp": 300},
        make_participant_headers(env["participant_id"])))
    assert_fields(elected, {
        "contribution_rate_bp": 300,
        "rate_source": "PARTICIPANT_ELECTED",
    }, label="enrolment after the saver's own election")


def test_employer_may_not_read_the_account_balance_of_its_own_employee(api):
    """
    The account belongs to the employer's own active employee and the employer
    can read the enrolment behind it, but the account route does not admit the
    employer at all. The refusal is the role gate, which fires ahead of
    existence, so a real identifier still answers 403 rather than 404.

    "Balances are none of an employer's business: the participant-account,
    excess-contribution-case and portability-transfer collections do not admit
    the `Employer` role at all, so an employer reaching for them is refused with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/employer_read_of_a_participant_account_is_unauthorized
    """
    env = build_active_saver_environment(api)
    employer_headers = make_employer_headers(env["employer_id"])

    account_attempt = api.get_participant_account(
        env["account_id"], employer_headers)

    validate_error(account_attempt, ERR_UNAUTHORIZED)
    assert account_attempt.status_code == 403, (
        "the role gate must answer 403 even for an account identifier that "
        f"exists, got {account_attempt.status_code}"
    )

    enrollment = validate_success(
        api.get_enrollment(env["enrollment_id"], employer_headers))
    assert_fields(enrollment, {
        "employer_id": env["employer_id"],
        "participant_id": env["participant_id"],
    }, label="enrolment the employer is entitled to read")


def test_each_exclusive_operation_refuses_the_peer_role_that_reaches_for_it(api):
    """
    Opening a payroll batch belongs to the employer, deciding a certification to
    the programme administrator, and posting money to the recordkeeper. A saver,
    a recordkeeper and a compliance officer each reach for the one that is not
    theirs and all three are refused identically, leaving every addressed row in
    the state it was already in.

    "If the role in `X-User-Role` is not among the roles the endpoint admits, the
    request fails with `ERR_UNAUTHORIZED` (HTTP 403), again before existence is
    checked, so a caller with the wrong role cannot use 404-versus-403 responses
    to probe which identifiers exist."

    Design: Corner/rbac/exclusive_operations_are_unauthorized_for_every_other_role
    """
    env = build_active_saver_environment(api)
    exemption = file_exemption(api, env["employer_id"])
    set_clock(api, "2026-02-05T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-01-01",
                              "2026-01-31", "2026-02-05", 400000)

    saver_opening_a_batch = api.create_payroll_remittance(
        env["employer_id"],
        {"pay_period_start": "2026-02-01", "pay_period_end": "2026-02-28",
         "pay_date": "2026-03-05", "total_deducted_cents": 400000},
        make_participant_headers(env["participant_id"]))
    recordkeeper_deciding_a_certification = api.decide_exemption_certification(
        exemption["id"], {"decision": "APPROVE"}, RECORDKEEPER)
    officer_posting_money = api.post_remittance(
        batch["id"], {"posting_reference": "ACH-OFFICER"}, OFFICER_A)

    validate_error(saver_opening_a_batch, ERR_UNAUTHORIZED)
    validate_error(recordkeeper_deciding_a_certification, ERR_UNAUTHORIZED)
    validate_error(officer_posting_money, ERR_UNAUTHORIZED)

    assert_total_count(
        api.list_payroll_remittances(ADMIN, {"employer_id": env["employer_id"]}),
        1, label="payroll batches of the employer")
    assert_fields(read_exemption(api, exemption["id"]), {
        "status": "SUBMITTED",
        "decided_at": None,
    }, label="certification nobody was authorised to decide")
    assert_fields(read_remittance(api, batch["id"]), {
        "status": "DRAFT",
        "posting_reference": None,
    }, label="batch nobody was authorised to post")


def test_the_assessing_officer_may_not_dispose_of_their_own_penalty(api):
    """
    Both officers hold the identical role and the cure period has genuinely run
    out, so nothing is left to refuse the assessor except their own recorded
    identity. The second officer's byte-identical request is accepted and is
    recorded as the disposing actor.

    "A `ComplianceOfficer` disposes of an assessment by supplying `disposition`
    as either `AFFIRM` or `ABATE`, with an optional `disposition_note`, and the
    disposing officer's `X-User-ID` must differ from the assessment's
    `assessed_by_user_id`; an officer disposing of their own assessment is
    refused with `ERR_SELF_DISPOSITION_FORBIDDEN`."

    Design: Corner/rbac/same_officer_cannot_dispose_of_the_penalty_they_assessed
    """
    env = build_employer_environment(api)
    set_clock(api, "2026-01-05T00:00:00Z")
    penalty = validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_REGISTER", "notice_date": "2026-01-05",
         "cure_days": 30},
        OFFICER_A), expected_status=201)
    assert_fields(penalty, {
        "assessed_by_user_id": OFFICER_A_USER_ID,
        "cure_deadline": "2026-02-04",
    }, label="assessment raised by the first officer")
    set_clock(api, "2026-02-05T00:00:00Z")

    self_disposition = api.dispose_penalty_assessment(
        penalty["id"],
        {"disposition": "AFFIRM",
         "disposition_note": "Self-affirmation attempt by the assessing officer"},
        OFFICER_A)

    validate_error(self_disposition, ERR_SELF_DISPOSITION_FORBIDDEN)
    assert_fields(read_penalty(api, penalty["id"]), {
        "status": "ASSESSED",
        "disposed_by_user_id": None,
    }, label="assessment after its own assessor tried to affirm it")

    affirmed = validate_success(api.dispose_penalty_assessment(
        penalty["id"],
        {"disposition": "AFFIRM",
         "disposition_note": "Reviewed by a second officer; no cure received"},
        OFFICER_B))
    assert_fields(affirmed, {
        "status": "AFFIRMED",
        "disposed_by_user_id": OFFICER_B_USER_ID,
        "disposition_note": "Reviewed by a second officer; no cure received",
    }, label="assessment affirmed by a second officer")


def test_a_saver_reaching_for_another_savers_account_is_out_of_scope(api):
    """
    Two savers hold the same role, so the role gate lets both through and the
    separation is done entirely by identity. Because ownership is evaluated after
    existence, a real foreign account and a fabricated identifier answer
    differently, and the saver's own account still reads normally.

    "A `Participant` owns every decision about their own money — deferral rate,
    escalation preference, opt-out and permissible withdrawal, fund allocation,
    excess-correction method, portability and account closure — but may read or
    write only their own participant record, enrolments, accounts, elections,
    excess cases and transfers; touching another saver's resources yields
    `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/participant_reading_another_participants_account_is_forbidden_scope
    """
    env = _two_savers_with_their_own_accounts(api)
    first, second = env["savers"]
    first_headers = make_participant_headers(first["participant"]["id"])

    foreign_read = api.get_participant_account(
        second["account"]["id"], first_headers)
    fabricated_read = api.get_participant_account(
        NON_EXISTENT_UUID, first_headers)
    own_read = api.get_participant_account(first["account"]["id"], first_headers)

    validate_error(foreign_read, ERR_FORBIDDEN_SCOPE)
    validate_error(fabricated_read, ERR_ACCOUNT_NOT_FOUND)
    own_account = validate_success(own_read)
    assert_fields(own_account, {
        "participant_id": first["participant"]["id"],
        "account_status": "OPEN",
    }, label="the saver's own account")


def test_the_service_centre_administrator_records_the_savers_own_decisions(api):
    """
    An administrator taking a telephone call may set the deferral rate, change
    the fund allocation and correct contact details with exactly the effect the
    saver would have had: the provenance fields record whose decision it was, not
    which principal typed it.

    "A saver changes funds by creating a new investment election on the account,
    which either the `Participant` who owns it or a `ProgramAdministrator` may
    do; the `Employer` role is not admitted to this operation at all, so an
    employer attempt is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/program_administrator_may_act_on_the_participants_behalf
    """
    env = build_active_saver_environment(api)
    account_version = read_account(api, env["account_id"])["version"]

    rate = validate_success(api.elect_contribution_rate(
        env["enrollment_id"],
        {"contribution_rate_bp": 700, "escalation_opt_out": True}, ADMIN))
    election = validate_success(api.create_investment_election(
        env["account_id"],
        {"allocations": [{"fund_code": "MMKT01", "allocation_bp": 10000}],
         "expected_account_version": account_version},
        ADMIN), expected_status=201)
    contact = validate_success(api.update_participant(
        env["participant_id"], {"phone": "+1-555-0142"}, ADMIN))

    assert_fields(rate, {
        "contribution_rate_bp": 700,
        "rate_source": "PARTICIPANT_ELECTED",
        "escalation_opt_out": True,
    }, label="enrolment after the service-centre rate election")
    assert_fields(election, {
        "source": "PARTICIPANT_ELECTED",
        "status": "ACTIVE",
        "selection_basis": None,
    }, label="election created in the service centre")
    assert read_account(api, env["account_id"])["active_election_id"] == (
        election["id"])
    assert_fields(contact, {"phone": "+1-555-0142"},
                  label="saver after the service-centre contact update")
    assert read_participant(api, env["participant_id"])["phone"] == "+1-555-0142"
