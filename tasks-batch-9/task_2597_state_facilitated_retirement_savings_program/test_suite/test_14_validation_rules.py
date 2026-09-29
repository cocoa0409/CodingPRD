"""
Validation rules at their exact boundaries.

Each scenario below pushes one documented rule to the edge where an off-by-one
comparison, a hoisted cheap check or a blanket refusal would show up: the
allocation arithmetic of a fund election, the closed contribution-rate band, the
reconciliation of a payroll batch against its declared total, the two saver-side
windows, the cure period of a penalty, the half-open coverage interval of a
qualified-plan exemption, and the fixed order in which a single request that
breaks several rules at once is refused.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    CLOCK_2026_03_06,
    EMPLOYER_RIDGE,
    ERR_ALLOCATION_TOTAL_INVALID,
    ERR_CURE_PERIOD_ACTIVE,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_EXEMPTION_PERIOD_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_OPT_OUT_WINDOW_CLOSED,
    ERR_PENALTY_NOT_FOUND,
    ERR_PERMISSIBLE_WITHDRAWAL_WINDOW_CLOSED,
    ERR_RATE_OUT_OF_BOUNDS,
    ERR_REMITTANCE_TOTAL_MISMATCH,
    ERR_UNAUTHORIZED,
    OFFICER_A,
    OFFICER_B,
    OFFICER_B_USER_ID,
    assert_amounts,
    assert_basis_points,
    assert_fields,
    assert_total_count,
    assess_penalty,
    build_active_saver_environment,
    build_employer_environment,
    build_notified_saver,
    build_program_configuration,
    create_participant,
    decide_exemption,
    fund_account_by_remittance,
    make_employer_headers,
    make_participant_headers,
    read_account,
    read_employer,
    read_enrollment,
    read_exemption,
    read_penalty,
    read_remittance,
    set_clock,
)

# An identifier that belongs to no row in any collection.
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def test_fund_allocation_must_reconcile_to_the_whole_before_it_is_accepted(api):
    """
    Three different ways of breaking the same allocation arithmetic — weights
    that fall a basis point short, one fund named twice, and a leg carrying no
    weight at all — are each refused, and because a refused election mutates
    nothing the saver's next attempt succeeds against the very same account
    version the three refusals quoted.

    "The weights must then sum to exactly 10000, every individual
    `allocation_bp` must be strictly greater than zero, and no `fund_code` may
    appear twice; any of those three failures is refused with
    `ERR_ALLOCATION_TOTAL_INVALID`, and because fund availability is checked
    first, an election naming a terminated fund reports the fund problem rather
    than the arithmetic one."

    Design: Corner/validations/investment_election_rejects_an_allocation_set_that_does_not_total_ten_thousand
    """
    env = build_active_saver_environment(api)
    saver_headers = make_participant_headers(env["participant_id"])
    observed_version = read_account(api, env["account_id"])["version"]

    for allocations in (
        [{"fund_code": "TDF2045", "allocation_bp": 5000},
         {"fund_code": "MMKT01", "allocation_bp": 4999}],
        [{"fund_code": "TDF2045", "allocation_bp": 5000},
         {"fund_code": "TDF2045", "allocation_bp": 5000}],
        [{"fund_code": "TDF2045", "allocation_bp": 10000},
         {"fund_code": "MMKT01", "allocation_bp": 0}],
    ):
        validate_error(
            api.create_investment_election(
                env["account_id"],
                {"allocations": allocations,
                 "expected_account_version": observed_version},
                saver_headers),
            ERR_ALLOCATION_TOTAL_INVALID)

    assert read_account(api, env["account_id"])["version"] == observed_version

    elected = validate_success(
        api.create_investment_election(
            env["account_id"],
            {"allocations": [{"fund_code": "TDF2045", "allocation_bp": 6000},
                             {"fund_code": "MMKT01", "allocation_bp": 4000}],
             "expected_account_version": observed_version},
            saver_headers),
        expected_status=201)

    assert_fields(elected, {
        "status": "ACTIVE",
        "source": "PARTICIPANT_ELECTED",
    }, label="accepted fund election")
    account = read_account(api, env["account_id"])
    assert account["active_election_id"] == elected["id"]
    assert_total_count(
        api.list_investment_elections(env["account_id"], ADMIN), 2,
        label="election history after one accepted change")


def test_the_deferral_rate_band_is_closed_on_both_of_its_ends(api):
    """
    One basis point below the statutory floor and one above the ceiling are both
    refused while the enrolment keeps the programme default, yet the floor and
    the ceiling themselves are accepted and recorded as the saver's own choice.

    "The elected rate must be at least 100 basis points and no more than 1500
    basis points — one percent to fifteen percent of gross wages — and a value
    outside that band is refused with `ERR_RATE_OUT_OF_BOUNDS`; a saver who
    wants to contribute nothing expresses that as an opt-out, not as a rate of
    zero."

    Design: Corner/validations/participant_rate_election_rejects_ninety_nine_bp_and_admits_one_hundred_bp
    """
    env = build_employer_environment(api)
    build_notified_saver(api, env)
    saver_headers = make_participant_headers(env["participant_id"])

    for rejected_rate in (99, 1501):
        validate_error(
            api.elect_contribution_rate(
                env["enrollment_id"], {"contribution_rate_bp": rejected_rate},
                saver_headers),
            ERR_RATE_OUT_OF_BOUNDS)

    untouched = read_enrollment(api, env["enrollment_id"])
    assert_basis_points(untouched["contribution_rate_bp"], 500,
                        "rate after both refusals")
    assert untouched["rate_source"] == "DEFAULT"

    at_the_floor = validate_success(api.elect_contribution_rate(
        env["enrollment_id"], {"contribution_rate_bp": 100}, saver_headers))
    assert_basis_points(at_the_floor["contribution_rate_bp"], 100,
                        "rate elected at the floor")
    assert at_the_floor["rate_source"] == "PARTICIPANT_ELECTED"

    at_the_ceiling = validate_success(api.elect_contribution_rate(
        env["enrollment_id"], {"contribution_rate_bp": 1500}, saver_headers))
    assert_basis_points(at_the_ceiling["contribution_rate_bp"], 1500,
                        "rate elected at the ceiling")
    assert_fields(at_the_ceiling, {
        "rate_source": "PARTICIPANT_ELECTED",
        "enrollment_status": "NOTIFIED",
    }, label="enrolment after the ceiling election")


def test_a_batch_may_not_be_handed_over_until_its_lines_add_up_to_its_total(api):
    """
    A batch declaring 400000 cents is refused while it carries no lines at all,
    and refused again while its single line — itself exactly right against the
    saver's own rate — leaves it 100000 cents short; the missing line makes the
    identical submission succeed and freezes lateness at zero.

    "The batch must be in `DRAFT` or `REJECTED`; it must have at least one line;
    the sum of its lines' `deducted_cents` must equal its declared
    `total_deducted_cents`, failing which the submission is refused with
    `ERR_REMITTANCE_TOTAL_MISMATCH`; and its pay period must still not overlap
    another live batch of the employer."

    Design: Corner/validations/remittance_submit_rejects_a_line_total_that_disagrees_with_the_batch_total
    """
    env = build_active_saver_environment(api)
    employer_headers = make_employer_headers(env["employer_id"])
    set_clock(api, CLOCK_2026_03_06)
    batch = validate_success(api.create_payroll_remittance(
        env["employer_id"],
        {"pay_period_start": "2026-02-01", "pay_period_end": "2026-02-28",
         "pay_date": "2026-03-05", "total_deducted_cents": 400000},
        employer_headers), expected_status=201)

    validate_error(api.submit_remittance(batch["id"], employer_headers),
                   ERR_REMITTANCE_TOTAL_MISMATCH)

    validate_success(api.create_remittance_line(
        batch["id"],
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 6000000,
         "deducted_cents": 300000},
        employer_headers), expected_status=201)
    validate_error(api.submit_remittance(batch["id"], employer_headers),
                   ERR_REMITTANCE_TOTAL_MISMATCH)
    assert read_remittance(api, batch["id"])["status"] == "DRAFT"

    validate_success(api.create_remittance_line(
        batch["id"],
        {"enrollment_id": env["enrollment_id"], "gross_wages_cents": 2000000,
         "deducted_cents": 100000},
        employer_headers), expected_status=201)
    submitted = validate_success(
        api.submit_remittance(batch["id"], employer_headers))

    assert_fields(submitted, {
        "status": "SUBMITTED",
        "line_count": 2,
        "days_late": 0,
    }, label="batch that finally reconciles")


def test_the_pre_activation_opt_out_closes_on_the_deadline_day_itself(api):
    """
    A saver noticed on the first of January has until the thirtieth to refuse
    before activation: on the deadline day of the thirty-first the refusal is
    already too late, while the day before it is accepted and moves no money.

    "From `NOTIFIED`, the opt-out is a pre-activation refusal and is only
    available while the clock date is strictly before `opt_out_deadline`; on or
    after that date the request is refused with `ERR_OPT_OUT_WINDOW_CLOSED` and
    the saver must instead wait for activation and opt out of an `ACTIVE`
    enrolment."

    Design: Corner/validations/opt_out_on_the_deadline_day_is_rejected_and_the_day_before_is_admitted
    """
    env = build_employer_environment(api)
    build_notified_saver(api, env)
    saver_headers = make_participant_headers(env["participant_id"])
    assert read_enrollment(api, env["enrollment_id"])["opt_out_deadline"] == (
        "2026-01-31")

    set_clock(api, "2026-01-31T00:00:00Z")
    validate_error(
        api.opt_out_enrollment(env["enrollment_id"],
                               {"opt_out_reason_code": "AFFORDABILITY"},
                               saver_headers),
        ERR_OPT_OUT_WINDOW_CLOSED)
    assert read_enrollment(api, env["enrollment_id"])["enrollment_status"] == (
        "NOTIFIED")

    set_clock(api, "2026-01-30T00:00:00Z")
    refused = validate_success(api.opt_out_enrollment(
        env["enrollment_id"], {"opt_out_reason_code": "AFFORDABILITY"},
        saver_headers))

    assert_fields(refused, {
        "enrollment_status": "OPTED_OUT",
        "opt_out_reason_code": "AFFORDABILITY",
    }, label="enrolment refused a day before the deadline")
    assert_amounts(refused, {"permissible_withdrawal_cents": 0},
                   label="pre-activation opt-out")


def test_an_unknown_employer_in_the_path_is_reported_before_a_short_payload(api):
    """
    An enrolment request that both addresses an employer that does not exist and
    omits the hire date reports the missing employer, never the missing field;
    the same short payload against a real employer is what produces the
    request-shape refusal.

    "On every endpoint with an identifier segment in its path, an unknown
    identifier yields that collection's not-found error."

    Design: Corner/validations/unknown_employer_in_the_path_outranks_a_malformed_body_and_is_not_found
    """
    env = build_employer_environment(api)
    saver = create_participant(api)
    short_payload = {"participant_id": saver["id"],
                     "annual_compensation_cents": 9600000}

    validate_error(
        api.create_enrollment(UNKNOWN_ID, dict(short_payload), ADMIN),
        ERR_EMPLOYER_NOT_FOUND)
    validate_error(
        api.create_enrollment(env["employer_id"], dict(short_payload), ADMIN),
        ERR_INVALID_REQUEST)

    assert_total_count(api.list_enrollments(ADMIN), 0,
                       label="enrolments after both refusals")


def test_a_saver_probing_an_enforcement_record_is_stopped_by_the_role_gate(api):
    """
    The disposition of a penalty is enforcement work: a saver reaching for one
    is refused on the role alone and learns nothing about whether the identifier
    exists, while the officer entitled to the route gets the plain not-found.

    "If the role in `X-User-Role` is not among the roles the endpoint admits, the
    request fails with `ERR_UNAUTHORIZED` (HTTP 403), again before existence is
    checked, so a caller with the wrong role cannot use 404-versus-403 responses
    to probe which identifiers exist."

    Design: Corner/validations/role_gate_outranks_the_unknown_penalty_id_and_returns_unauthorized
    """
    build_program_configuration(api)
    saver = create_participant(api)

    validate_error(
        api.dispose_penalty_assessment(
            UNKNOWN_ID, {"disposition": "ABATE"},
            make_participant_headers(saver["id"])),
        ERR_UNAUTHORIZED)
    validate_error(
        api.dispose_penalty_assessment(
            UNKNOWN_ID, {"disposition": "ABATE"}, OFFICER_A),
        ERR_PENALTY_NOT_FOUND)


def test_the_permissible_withdrawal_closes_thirty_days_after_the_first_deposit(api):
    """
    The statutory refund of everything already withheld runs for thirty days
    from the first contribution: asked for on the thirty-first day it is refused
    and the enrolment stays live, asked for on the thirtieth it returns the whole
    400000 cents of lifetime deductions and empties the account.

    "When `request_permissible_withdrawal` is true, the withdrawal is available
    only inside the statutory window that opens at the saver's first
    contribution: `first_contribution_date` must be non-null and the clock date
    must be no later than `first_contribution_date` plus the program year's
    `opt_out_window_days`."

    Design: Corner/validations/permissible_withdrawal_requested_after_the_window_is_rejected
    """
    env = build_active_saver_environment(api)
    fund_account_by_remittance(api, env, "2026-02-01", "2026-02-28",
                               "2026-03-05", 8000000, 400000, CLOCK_2026_03_06)
    saver_headers = make_participant_headers(env["participant_id"])
    seeded = read_enrollment(api, env["enrollment_id"])
    assert seeded["first_contribution_date"] == "2026-03-05"
    assert_amounts(seeded, {"lifetime_deducted_cents": 400000},
                   label="enrolment after its first posting")

    set_clock(api, "2026-04-05T00:00:00Z")
    validate_error(
        api.opt_out_enrollment(
            env["enrollment_id"],
            {"opt_out_reason_code": "AFFORDABILITY",
             "request_permissible_withdrawal": True},
            saver_headers),
        ERR_PERMISSIBLE_WITHDRAWAL_WINDOW_CLOSED)
    still_live = read_enrollment(api, env["enrollment_id"])
    assert still_live["enrollment_status"] == "ACTIVE"
    assert_amounts(still_live, {"permissible_withdrawal_cents": 0},
                   label="enrolment after the late request")

    set_clock(api, "2026-04-04T00:00:00Z")
    withdrawn = validate_success(api.opt_out_enrollment(
        env["enrollment_id"],
        {"opt_out_reason_code": "AFFORDABILITY",
         "request_permissible_withdrawal": True},
        saver_headers))

    assert withdrawn["enrollment_status"] == "OPTED_OUT"
    assert_amounts(withdrawn, {"permissible_withdrawal_cents": 400000},
                   label="enrolment refunded inside the window")
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": 0,
        "contribution_basis_cents": 0,
    }, label="account after the permissible withdrawal")


def test_a_penalty_cannot_be_affirmed_on_the_last_day_of_its_cure_period(api):
    """
    A notice dated the first of February with a thirty-day cure period runs
    through the third of March inclusive: an affirmation raised on that day is
    refused and leaves the assessment undisposed, while the fourth of March is
    the first day the second officer's affirmation sticks.

    "Affirmation is available only from `ASSESSED`, and only once the cure period
    has genuinely run out: the clock date must be later than `cure_deadline`, and
    an affirmation on or before that date is refused with
    `ERR_CURE_PERIOD_ACTIVE`."

    Design: Corner/validations/penalty_affirmation_inside_the_cure_period_is_rejected
    """
    env = build_employer_environment(api, employer=EMPLOYER_RIDGE,
                                     register=False)
    set_clock(api, "2026-03-03T00:00:00Z")
    penalty = assess_penalty(api, env["employer_id"], "FAILURE_TO_REGISTER",
                             "2026-02-01", 30, headers=OFFICER_A)
    assert penalty["cure_deadline"] == "2026-03-03"

    validate_error(
        api.dispose_penalty_assessment(
            penalty["id"],
            {"disposition": "AFFIRM",
             "disposition_note": "Raised on the cure deadline itself"},
            OFFICER_B),
        ERR_CURE_PERIOD_ACTIVE)
    undisposed = read_penalty(api, penalty["id"])
    assert undisposed["status"] == "ASSESSED"
    assert undisposed["disposed_by_user_id"] is None

    set_clock(api, "2026-03-04T00:00:00Z")
    affirmed = validate_success(api.dispose_penalty_assessment(
        penalty["id"],
        {"disposition": "AFFIRM",
         "disposition_note": "Cure period elapsed with no registration"},
        OFFICER_B))

    assert_fields(affirmed, {
        "status": "AFFIRMED",
        "disposed_by_user_id": OFFICER_B_USER_ID,
    }, label="assessment affirmed after the cure period")
    assert read_employer(api, env["employer_id"])["compliance_status"] == (
        "PENALIZED")


def test_an_exemption_may_abut_a_live_coverage_window_but_not_reach_into_it(api):
    """
    Three-year coverage is open at its far end, so a plan effective one day
    before an approved window closes collides with it, while a plan effective on
    the very day it closes is filed without complaint and starts its own
    three-year window there.

    "A new certification is refused with `ERR_EXEMPTION_PERIOD_OVERLAP` when that
    half-open interval intersects the interval of another certification of the
    same employer whose status is `SUBMITTED` or `APPROVED`."

    Design: Corner/validations/exemption_filing_rejects_an_overlap_but_admits_an_abutting_half_open_interval
    """
    env = build_employer_environment(api, employer=EMPLOYER_RIDGE,
                                     register=False)
    employer_headers = make_employer_headers(env["employer_id"])
    filing = {"qualified_plan_type": "401K",
              "plan_sponsor_ein": "77-8889990",
              "plan_effective_date": "2026-01-01",
              "attestation_accepted": True}
    approved = validate_success(api.create_exemption_certification(
        env["employer_id"], dict(filing), employer_headers),
        expected_status=201)
    decide_exemption(api, approved["id"], "APPROVE", "Plan document verified")
    assert_fields(read_exemption(api, approved["id"]), {
        "status": "APPROVED",
        "coverage_period_start": "2026-01-01",
        "coverage_period_end": "2029-01-01",
    }, label="approved certification")

    overlapping = dict(filing, plan_effective_date="2028-12-31")
    validate_error(api.create_exemption_certification(
        env["employer_id"], overlapping, employer_headers),
        ERR_EXEMPTION_PERIOD_OVERLAP)

    abutting = validate_success(api.create_exemption_certification(
        env["employer_id"], dict(filing, plan_effective_date="2029-01-01"),
        employer_headers), expected_status=201)

    assert_fields(abutting, {
        "status": "SUBMITTED",
        "coverage_period_start": "2029-01-01",
        "coverage_period_end": "2032-01-01",
    }, label="certification abutting the approved window")
    assert_total_count(
        api.list_employer_exemption_certifications(env["employer_id"], ADMIN), 2,
        label="certifications of the employer")
