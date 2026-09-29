"""Error corners on the state, ceiling and duty-separation rungs of the ladder."""
from test_helpers import (
    ApiErrorId,
    begin_review,
    build_active_determination,
    build_assignment,
    build_contractor,
    build_finding,
    build_fringe_plan,
    build_interview,
    build_payment,
    build_portal,
    build_project,
    build_submission,
    build_worker,
    certify,
    compliant_paid_line,
    get_success_data,
    move_clock,
    read_assignment,
    rule_on_fringe_plan,
    setup_accepted_submission,
    setup_env,
    setup_env_with_worker,
    setup_finalized_submission,
    validate_error,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]
APPRENTICE_RATES = [{"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}]
# 40 h paid 4000 + 2000 cash against a required 5000 + 2000: 1000 short per hour, 40000 in all.
DEFICIENT_LINE = {
    "straight_hours": 40.00,
    "overtime_hours": 0.00,
    "base_rate_paid_cents": 4000,
    "overtime_rate_paid_cents": 0,
    "fringe_cash_paid_cents": 2000,
}


def _deficient_submitted_week(api):
    """A certified, SUBMITTED week whose make_whole_underpayment_cents is exactly 40000."""
    env, submission, rows = setup_finalized_submission(
        api, lines=[dict(DEFICIENT_LINE)], week_ending_date=WEEK, rates=ONE_RATE
    )
    assert submission["compliance_status"] == "DEFICIENT"
    assert submission["make_whole_underpayment_cents"] == 40000
    submission = certify(api, env, submission["id"])
    assert submission["workflow_status"] == "SUBMITTED"
    return env, submission, rows


def test_finalizing_a_week_with_no_lines_and_no_no_work_flag_is_refused(api, portal_admin_headers):
    """An empty week is legal only when it is declared empty, and the default flag is false.

    PRD 3.6: "The line inventory must be internally consistent: either the submission carries at
    least one payroll line and `no_work_performed` is false, or it carries zero lines and
    `no_work_performed` is true — a zero-line submission with the flag false, and a submission
    carrying lines with the flag true, are both refused with `ERR_EMPTY_PAYROLL`." PRD 3.5:
    "`no_work_performed`, a flag that defaults to false".

    Design: Corner/errors/finalizing_a_week_with_no_lines_and_no_no_work_flag_is_refused
    """
    env = setup_env(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=WEEK)
    assert submission["no_work_performed"] is False
    move_clock(api, WEEK)

    resp = api.finalize_payroll_submission(submission["id"], env["preparer_headers"])
    validate_error(resp, ApiErrorId.ERR_EMPTY_PAYROLL.value, expected_status=422)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert unchanged["compliance_status"] == "UNVERIFIED"


def test_a_cash_in_lieu_plan_plus_cash_on_the_same_line_is_refused(api, officer_headers):
    """The rule fires on the combination: the same plan with zero cash would have been legal.

    PRD 3.5: "Fringe may not be counted twice: a line may not simultaneously name a plan whose
    `plan_type` is `CASH_IN_LIEU` and report a `fringe_cash_paid_cents` greater than 0, and a line
    that does both is refused with `ERR_FRINGE_DOUBLE_COUNT`."

    Design: Corner/errors/a_cash_in_lieu_plan_plus_cash_on_the_same_line_is_refused
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    plan = build_fringe_plan(
        api, env["contractor"]["id"], env["preparer_headers"],
        plan_name="Acme Cash In Lieu", plan_type="CASH_IN_LIEU",
    )
    rule_on_fringe_plan(api, plan["id"], "APPROVED", officer_headers)
    submission = build_submission(api, env, week_ending_date=WEEK)

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": env["worker"]["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 40.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 5000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
            "fringe_plan_id": plan["id"],
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FRINGE_DOUBLE_COUNT.value, expected_status=422)
    assert get_success_data(
        api.get_payroll_submission(submission["id"], officer_headers)
    )["workflow_status"] == "DRAFT"


def test_a_rejected_fringe_plan_cannot_back_a_payroll_line(api, officer_headers):
    """REJECTED is a hard refusal, unlike PENDING_APPROVAL which merely credits nothing.

    PRD 3.3: "A plan still sitting in `PENDING_APPROVAL` credits nothing, but it is not an error
    to name it on a line; a plan that has been `REJECTED` may not be named on a line at all, and
    doing so is refused with `ERR_FRINGE_PLAN_NOT_APPROVED`."

    Design: Corner/errors/a_rejected_fringe_plan_cannot_back_a_payroll_line
    """
    env = setup_env_with_worker(api, rates=ONE_RATE)
    plan = build_fringe_plan(
        api, env["contractor"]["id"], env["preparer_headers"],
        plan_name="Acme Refused Trust", plan_type="BONA_FIDE_TRUST",
    )
    rejected = rule_on_fringe_plan(api, plan["id"], "REJECTED", officer_headers)
    assert rejected["approval_status"] == "REJECTED"
    submission = build_submission(api, env, week_ending_date=WEEK)

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": env["worker"]["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 40.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 5000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 0,
            "fringe_plan_id": plan["id"],
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FRINGE_PLAN_NOT_APPROVED.value, expected_status=422)
    plans = get_success_data(api.list_fringe_plans(env["contractor"]["id"], officer_headers))
    assert [row["approval_status"] for row in plans if row["id"] == plan["id"]] == ["REJECTED"]


def test_an_apprentice_period_beyond_the_published_scale_is_refused(api, portal_admin_headers):
    """The published scale, not the program's period count, is the binding ceiling.

    PRD 3.5: "the worker's `apprentice_period` must be no greater than both the length of the
    matched row's `apprentice_scale_pct` array and the program's `period_count`, or the line is
    refused with `ERR_APPRENTICE_PERIOD_OUT_OF_SCALE`."

    Design: Corner/errors/an_apprentice_period_beyond_the_published_scale_is_refused
    """
    env = setup_env(
        api, rates=APPRENTICE_RATES,
        with_program={"trade_code": "ELEC", "registration_status": "REGISTERED", "period_count": 6},
    )
    assert env["program"]["period_count"] == 6
    assert len(env["rate"]["apprentice_scale_pct"]) == 4
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=5,
    )
    assert apprentice["apprentice_period"] == 5
    submission = build_submission(api, env, week_ending_date=WEEK)

    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": apprentice["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 8.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 4000,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
            "reported_as_apprentice": True,
        },
        env["preparer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_PERIOD_OUT_OF_SCALE.value, expected_status=422)
    assert get_success_data(
        api.get_payroll_submission(submission["id"], portal_admin_headers)
    )["workflow_status"] == "DRAFT"


def test_accepting_a_deficient_week_is_refused(api, officer_headers):
    """The one workflow transition gated by the compliance axis, and no hours are credited.

    PRD 3.8: "Acceptance advances the axis `UNDER_REVIEW → ACCEPTED` and requires no payload, but
    it is gated on the compliance axis: a submission whose `compliance_status` is `DEFICIENT` may
    not be accepted, and the attempt is refused with `ERR_UNDERPAYMENT_UNRESOLVED`."

    Design: Corner/errors/accepting_a_deficient_week_is_refused
    """
    env, submission, _rows = _deficient_submitted_week(api)
    reviewed = begin_review(api, submission["id"])
    assert reviewed["workflow_status"] == "UNDER_REVIEW"

    resp = api.accept_payroll_submission(submission["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_UNDERPAYMENT_UNRESOLVED.value, expected_status=409)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert unchanged["workflow_status"] == "UNDER_REVIEW"
    assert unchanged["compliance_status"] == "DEFICIENT"
    assert unchanged["make_whole_underpayment_cents"] == 40000
    assert unchanged["accepted_by_user_id"] is None
    assert float(read_assignment(api, env["assignment"]["id"])["cumulative_certified_hours"]) == 0.00


def test_certifying_more_than_ninety_days_after_the_week_ends_is_refused(api, officer_headers):
    """Past the hard close the signature is refused outright, not merely stamped late.

    PRD 3.7: "There is also an outer boundary past which a portal simply will not accept paper. At
    signing time the logical clock must read at or before the submission's `week_ending_date`
    advanced by ninety days; a clock reading exactly at that hard-close instant is still accepted,
    while anything beyond it is refused with `ERR_SUBMISSION_WINDOW_CLOSED`. Note the difference
    between this and lateness — lateness is recorded, not refused."

    Design: Corner/errors/certifying_more_than_ninety_days_after_the_week_ends_is_refused
    """
    env, submission, _rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    assert submission["workflow_status"] == "PENDING_CERTIFICATION"
    # The 90th day after 2026-08-01 is 2026-10-30; the clock is moved six days past it.
    move_clock(api, "2026-11-05T00:00:00.000Z")

    resp = api.certify_payroll_submission(submission["id"], env["certifier_headers"], {})
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED.value, expected_status=409)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert unchanged["workflow_status"] == "PENDING_CERTIFICATION"
    assert unchanged["submitted_at"] is None
    assert unchanged["statement_signed_at"] is None


def test_restitution_demanded_above_the_computed_underpayment_is_refused(api, cruz_headers):
    """40001 is refused where 40000 would stand: the engine's own total is the ceiling.

    PRD 3.10: "When the `finding_type` is `UNDERPAYMENT`, the demanded `restitution_required_cents`
    may not exceed the cited submission's computed `make_whole_underpayment_cents`; the service's
    own authoritative arithmetic is the ceiling on the demand, and a larger figure is refused with
    `ERR_RESTITUTION_ABOVE_COMPUTED_UNDERPAYMENT`."

    Design: Corner/errors/restitution_demanded_above_the_computed_underpayment_is_refused
    """
    env, submission, rows = _deficient_submitted_week(api)

    resp = api.create_finding(
        {
            "project_id": env["project"]["id"],
            "payroll_submission_id": submission["id"],
            "worker_id": rows[0]["worker_id"],
            "finding_type": "UNDERPAYMENT",
            "severity": "MAJOR",
            "restitution_required_cents": 40001,
        },
        cruz_headers,
    )
    validate_error(
        resp, ApiErrorId.ERR_RESTITUTION_ABOVE_COMPUTED_UNDERPAYMENT.value, expected_status=422
    )

    assert get_success_data(
        api.get_payroll_submission(submission["id"], cruz_headers)
    )["make_whole_underpayment_cents"] == 40000
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 0
    assert project["posture"] == "OPEN"


def test_responding_to_a_withdrawn_finding_is_refused(api, cruz_headers):
    """WITHDRAWN is terminal, so a late response cannot resurrect the finding or its counters.

    PRD 3.10: "The finding must be in `OPEN` or `RESPONSE_REJECTED`; any other state is refused
    with `ERR_INVALID_FINDING_STATE`." PRD 3.10: "`RESPONSE_ACCEPTED` and `WITHDRAWN` are the two
    terminal states of a finding."

    Design: Corner/errors/responding_to_a_withdrawn_finding_is_refused
    """
    env, submission, rows = _deficient_submitted_week(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        worker_id=rows[0]["worker_id"], finding_type="UNDERPAYMENT",
        severity="MAJOR", restitution_required_cents=40000,
    )
    withdrawn = get_success_data(
        api.withdraw_finding(
            finding["id"],
            {"withdrawal_reason": "Referral duplicated an existing case file."},
            cruz_headers,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.file_finding_response(
        finding["id"],
        {
            "response_narrative": "The classification was correct as filed.",
            "expected_finding_version": withdrawn["version"],
        },
        env["certifier_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FINDING_STATE.value, expected_status=409)

    after = get_success_data(api.get_finding(finding["id"], cruz_headers))
    assert after["status"] == "WITHDRAWN"
    assert after["response_round"] == 0
    assert get_success_data(
        api.get_project(env["project"]["id"], cruz_headers)
    )["open_finding_count"] == 0


def test_disbursing_the_same_restitution_payment_twice_is_refused(api, officer_headers):
    """Disburse is not idempotent, and the second call must not debit the balance again.

    PRD 3.11: "The payment must be `PENDING`, or the request is refused with
    `ERR_INVALID_PAYMENT_STATE`". PRD 3.11: "Success moves the payment `PENDING → DISBURSED` and
    stamps `disbursed_at` with the current logical clock instant. It then reduces the finding's
    `restitution_outstanding_cents` by the paid amount".

    Design: Corner/errors/disbursing_the_same_restitution_payment_twice_is_refused
    """
    env, submission, rows = _deficient_submitted_week(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        worker_id=rows[0]["worker_id"], finding_type="UNDERPAYMENT",
        severity="MAJOR", restitution_required_cents=40000,
    )
    payment = build_payment(api, env, finding["id"], rows[0]["worker_id"], 40000)
    disbursed = get_success_data(
        api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    )
    assert disbursed["status"] == "DISBURSED"

    resp = api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_PAYMENT_STATE.value, expected_status=409)

    assert get_success_data(
        api.get_restitution_payment(payment["id"], officer_headers)
    )["status"] == "DISBURSED"
    assert get_success_data(
        api.get_finding(finding["id"], officer_headers)
    )["restitution_outstanding_cents"] == 0
    assert get_success_data(
        api.get_contractor(env["contractor"]["id"], officer_headers)
    )["outstanding_restitution_cents"] == 0
    assert read_assignment(api, env["assignment"]["id"])["cumulative_restitution_cents"] == 40000


def test_conducting_a_cancelled_interview_is_refused(api, cruz_headers):
    """The auto-finding cascade hangs off the transition, so a terminal interview raises nothing.

    PRD 3.9: "The interview must be `SCHEDULED`, or the request is refused with
    `ERR_INVALID_INTERVIEW_STATE`". PRD 3.9: "All three of `CONDUCTED_MATCHED`,
    `CONDUCTED_DISCREPANT` and `CANCELLED` are terminal."

    Design: Corner/errors/conducting_a_cancelled_interview_is_refused
    """
    env, submission, rows = setup_accepted_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    assert submission["workflow_status"] == "ACCEPTED"
    interview = build_interview(
        api, env, rows[0]["worker_id"],
        "2026-07-29T09:00:00.000Z", "2026-07-29T10:00:00.000Z",
    )
    cancelled = get_success_data(
        api.cancel_interview(
            interview["id"], {"cancellation_reason": "Auditor reassigned."}, cruz_headers
        )
    )
    assert cancelled["status"] == "CANCELLED"

    resp = api.conduct_interview(
        interview["id"],
        {"observed_classification_code": "ELEC-INSIDE-JW", "observed_hourly_rate_cents": 6000},
        cruz_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVIEW_STATE.value, expected_status=409)

    assert get_success_data(api.get_interview(interview["id"], cruz_headers))["status"] == "CANCELLED"
    assert get_success_data(
        api.get_project(env["project"]["id"], cruz_headers)
    )["open_finding_count"] == 0
    assert get_success_data(
        api.get_worker(rows[0]["worker_id"], cruz_headers)
    )["interview_count"] == 0


def test_a_lower_tier_cannot_activate_under_an_invited_upper_tier(api, portal_admin_headers):
    """The tier chain comes online strictly top-down, and the refusal freezes the whole project.

    PRD 3.4: "when the tier has an upper tier, that upper tier must itself be `ACTIVE` at this
    moment, or the activation fails with `ERR_UPPER_TIER_NOT_ACTIVE`. Subcontract tiers therefore
    come online strictly top-down." PRD 3.4: "Once at least one tier-0 assignment on the project is
    `ACTIVE`, a `PortalAdmin` may advance the project `AWARDED → ACTIVE`".

    Design: Corner/errors/a_lower_tier_cannot_activate_under_an_invited_upper_tier
    """
    portal = build_portal(api)
    determination, _rates = build_active_determination(api, rates=ONE_RATE)
    prime_firm = build_contractor(api, legal_name="Acme Electric")
    sub_firm = build_contractor(api, legal_name="Bay Conduit")
    project = build_project(api, determination["id"], portal["id"])
    prime = build_assignment(api, project["id"], prime_firm["id"])
    sub = build_assignment(
        api, project["id"], sub_firm["id"],
        upper_tier_assignment_id=prime["id"], subcontract_amount_cents=25000000,
    )
    assert prime["status"] == "INVITED"
    assert sub["tier"] == 1

    resp = api.activate_contract_assignment(sub["id"], portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_UPPER_TIER_NOT_ACTIVE.value, expected_status=409)

    assert read_assignment(api, sub["id"])["status"] == "INVITED"
    assert read_assignment(api, sub["id"])["tier"] == 1
    assert read_assignment(api, prime["id"])["status"] == "INVITED"
    assert get_success_data(api.get_project(project["id"], portal_admin_headers))["status"] == (
        "AWARDED"
    )


def test_the_officer_who_accepted_the_week_cannot_review_its_finding_response(
    api, officer_headers, cruz_headers
):
    """Agency-side segregation is keyed on the cited submission's stored accepted_by_user_id.

    PRD 3.10: "Before either outcome is evaluated, segregation of duties is enforced: the acting
    officer's `X-User-ID` must differ from the `accepted_by_user_id` recorded on the cited
    submission, so the officer who accepted a payroll may never adjudicate a finding raised against
    it, and the attempt is refused with `ERR_SOD_REVIEW_CONFLICT`." PRD 3.8: "Acceptance records
    the acting officer's `X-User-ID` in the submission's `accepted_by_user_id`, which is the value
    that will later block that same officer from adjudicating a finding raised against this very
    payroll."

    Design: Corner/errors/the_officer_who_accepted_the_week_cannot_review_its_finding_response
    """
    env, submission, rows = setup_accepted_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    accepted_by = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert accepted_by["accepted_by_user_id"] == officer_headers["X-User-ID"]

    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        worker_id=rows[0]["worker_id"], finding_type="APPRENTICE_RATIO",
        severity="MINOR", restitution_required_cents=0,
    )
    responded = get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Ratio was met once the second journeyworker is counted.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"

    resp = api.review_finding_response(
        finding["id"],
        {"decision": "ACCEPT", "reviewer_note": "Extract looks fine to me."},
        officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SOD_REVIEW_CONFLICT.value, expected_status=409)

    after = get_success_data(api.get_finding(finding["id"], cruz_headers))
    assert after["status"] == "RESPONSE_SUBMITTED"
    assert after["response_round"] == 1
    assert get_success_data(
        api.get_project(env["project"]["id"], cruz_headers)
    )["open_finding_count"] == 1
