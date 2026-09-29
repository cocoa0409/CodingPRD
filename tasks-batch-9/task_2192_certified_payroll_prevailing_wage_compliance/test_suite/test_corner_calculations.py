"""Wage-engine, posture and risk-score arithmetic at its declared corners."""
from test_helpers import (
    build_finding,
    build_line,
    build_program,
    build_submission,
    build_worker,
    certify,
    compliant_paid_line,
    finalize,
    fringe_plan_payload,
    get_success_data,
    move_clock,
    rule_on_fringe_plan,
    setup_env,
    setup_finalized_submission,
    validate_success,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]
PROGRAM_25 = {"allowed_apprentice_hours_per_100_journey": 25, "period_count": 4}
APPRENTICE_RATE = {"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}


def _approved_plan(api, env, officer_headers, **overrides):
    """A BONA_FIDE_TRUST plan on env's contractor, ruled APPROVED by the officer."""
    plan = get_success_data(
        api.create_fringe_plan(
            env["contractor"]["id"], fringe_plan_payload(**overrides), env["preparer_headers"]
        ),
        expected_status=201,
    )
    return rule_on_fringe_plan(api, plan["id"], "APPROVED", officer_headers)


def test_a_cash_in_lieu_plan_credits_nothing_on_either_variant(api):
    """Both stored credits short-circuit to zero however large the annual contribution is.

    PRD 3.3: "A plan whose `plan_type` is `CASH_IN_LIEU` skips both divisions: both
    `annualized_credit_cents` and `claimed_credit_cents` are set to 0, because cash in lieu of
    benefits is reported as cash on the payroll line and never as a plan credit." PRD 3.3: "A
    newly declared plan starts with `approval_status` `PENDING_APPROVAL`."

    Design: Corner/calculations/cash_in_lieu_plan_credits_nothing_on_either_variant
    """
    env = setup_env(api, rates=ONE_RATE)
    resp = api.create_fringe_plan(
        env["contractor"]["id"],
        fringe_plan_payload(
            plan_name="Cash In Lieu 2026",
            plan_type="CASH_IN_LIEU",
            annual_contribution_cents=6300000,
            annual_total_hours=2100.00,
            annual_public_works_hours=1050.00,
        ),
        env["preparer_headers"],
    )
    plan = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert plan["annualized_credit_cents"] == 0
    assert plan["claimed_credit_cents"] == 0
    assert plan["approval_status"] == "PENDING_APPROVAL"


def test_a_plan_the_line_does_not_name_contributes_no_credit(api, officer_headers):
    """A 3000-cent approved plan the line ignores leaves the whole 2000-cent fringe owing.

    PRD 3.6 step three: "A line that names no `fringe_plan_id` has a plan credit of zero. ...
    Plans that a contractor holds but that a line does not name contribute nothing to that
    line."

    Design: Corner/calculations/an_approved_plan_the_line_does_not_name_contributes_no_credit
    """
    env = setup_env(api, rates=ONE_RATE)
    plan = _approved_plan(
        api, env, officer_headers,
        annual_contribution_cents=6300000,
        annual_total_hours=2100.00,
        annual_public_works_hours=2100.00,
    )
    assert plan["annualized_credit_cents"] == 3000

    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date=WEEK)
    line = build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=0, fringe_cash_paid_cents=0,
    )
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line["id"], officer_headers))
    assert priced["creditable_fringe_cents"] == 0
    assert priced["required_base_cents"] == 5000
    assert priced["required_fringe_cents"] == 2000
    assert priced["line_underpayment_cents"] == 80000
    assert finalized["make_whole_underpayment_cents"] == 80000
    assert finalized["straight_time_underpayment_cents"] == 80000
    assert finalized["compliance_status"] == "DEFICIENT"


def test_plan_credit_is_capped_at_the_required_fringe_and_never_offsets_the_base(
    api, officer_headers
):
    """1000 cents of surplus credit is discarded and cannot paper over a 100-cent base shortfall.

    PRD 3.6 step three: "The line's `creditable_fringe_cents` is then the smaller of that plan
    credit and the line's own `required_fringe_cents`. That cap is deliberate and it is
    absolute: fringe credit in excess of the determination's fringe requirement is discarded at
    this point and can never be carried over to offset a shortfall in the basic rate."

    Design: Corner/calculations/plan_credit_is_capped_at_required_fringe_and_cannot_offset_the_base
    """
    env = setup_env(api, rates=ONE_RATE)
    plan = _approved_plan(
        api, env, officer_headers,
        annual_contribution_cents=6300000,
        annual_total_hours=2100.00,
        annual_public_works_hours=2100.00,
    )
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date=WEEK)
    line = build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=4900, overtime_rate_paid_cents=0, fringe_cash_paid_cents=0,
        fringe_plan_id=plan["id"],
    )
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line["id"], officer_headers))
    assert priced["creditable_fringe_cents"] == 2000
    assert priced["line_underpayment_cents"] == 4000
    assert finalized["make_whole_underpayment_cents"] == 4000
    assert finalized["straight_time_underpayment_cents"] == 4000
    assert finalized["compliance_status"] == "DEFICIENT"


def test_the_apprentice_scale_discounts_the_base_but_never_the_fringe(api, officer_headers):
    """A period-2 apprentice owes 60 percent of the base and the whole 2000-cent fringe.

    PRD 3.6 step two: "The line's `required_base_cents` is then the journeyworker basic rate
    multiplied by that percentage, divided by 100, and rounded half up to a whole cent. In every
    case — apprentice or journeyworker — the line's `required_fringe_cents` is the matched row's
    `fringe_hourly_rate_cents` in full. This is the pinned interpretation and it is worth stating
    flatly: the apprentice scale discounts the basic rate only, and an apprentice is owed the
    complete fringe amount an experienced journeyworker in the same classification is owed."

    Design: Corner/calculations/apprentice_scale_discounts_the_base_but_never_the_fringe
    """
    env = setup_env(api, rates=[dict(APPRENTICE_RATE)], with_program=PROGRAM_25)
    journeyworker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=2,
    )
    submission = build_submission(api, env, week_ending_date=WEEK)
    line_j = build_line(
        api, env, submission["id"], journeyworker["id"],
        **compliant_paid_line(fringe_cash_paid_cents=2000),
    )
    line_a = build_line(
        api, env, submission["id"], apprentice["id"],
        straight_hours=8.00, overtime_hours=0.00,
        base_rate_paid_cents=3000, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
        reported_as_apprentice=True,
    )
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    priced_a = get_success_data(api.get_payroll_line(line_a["id"], officer_headers))
    assert priced_a["required_base_cents"] == 3000
    assert priced_a["required_fringe_cents"] == 2000
    assert float(priced_a["reclassified_journey_hours"]) == 0.00
    assert priced_a["line_underpayment_cents"] == 0
    priced_j = get_success_data(api.get_payroll_line(line_j["id"], officer_headers))
    assert priced_j["required_base_cents"] == 5000

    assert float(finalized["excess_apprentice_hours"]) == 0.00
    assert float(finalized["total_hours_reported"]) == 48.00
    assert finalized["make_whole_underpayment_cents"] == 0
    assert finalized["compliance_status"] == "COMPLIANT"


def test_the_apprentice_scale_rounds_half_up_on_an_exact_half_cent(api, officer_headers):
    """5335 times 70 percent is 3734.5 cents, which rounds up to 3735 and costs 8 cents.

    PRD 2.5: "Wherever a monetary computation produces a non-integral intermediate — dividing an
    annual contribution by an hour count, scaling a journeyworker rate by an apprentice
    percentage, multiplying a per-hour deficiency by a fractional hour count, or applying the
    overtime factor — the result is rounded half up to a whole cent, meaning a value exactly at
    the half-cent boundary rounds away from zero to the larger magnitude." PRD 3.6 step two: "The line's
    `required_base_cents` is then the journeyworker basic rate multiplied by that percentage,
    divided by 100, and rounded half up to a whole cent."

    Design: Corner/calculations/apprentice_scale_rounds_half_up_on_a_half_cent_result
    """
    env = setup_env(
        api,
        rates=[dict(APPRENTICE_RATE, base_hourly_rate_cents=5335)],
        with_program=PROGRAM_25,
    )
    journeyworker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=3,
    )
    submission = build_submission(api, env, week_ending_date=WEEK)
    build_line(
        api, env, submission["id"], journeyworker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=5335, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
    )
    line_a = build_line(
        api, env, submission["id"], apprentice["id"],
        straight_hours=8.00, overtime_hours=0.00,
        base_rate_paid_cents=3734, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
        reported_as_apprentice=True,
    )
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    priced = get_success_data(api.get_payroll_line(line_a["id"], officer_headers))
    assert priced["required_base_cents"] == 3735
    assert priced["required_fringe_cents"] == 2000
    assert priced["line_underpayment_cents"] == 8
    assert finalized["make_whole_underpayment_cents"] == 8
    assert finalized["straight_time_underpayment_cents"] == 8
    assert finalized["compliance_status"] == "DEFICIENT"


def test_the_smallest_program_ratio_governs_and_the_largest_line_absorbs_first(
    api, officer_headers
):
    """Programs at 25 and 15 pin the week to 15, and the 14.00 excess drains line one first.

    PRD 3.6 step one: "The permitted ratio for that family is the smallest
    `allowed_apprentice_hours_per_100_journey` among the distinct apprenticeship programs
    referenced by that family's apprentice lines — the most restrictive program in the crew
    governs the whole crew". PRD 3.6: "The candidate lines for a trade family are that family's
    lines whose `reported_as_apprentice` is true, ordered by descending total hours — straight
    plus overtime — with ties broken by ascending `created_at` on the payroll line. Walking that
    order, each candidate absorbs into its `reclassified_journey_hours` either the whole
    remaining excess or its own total hours, whichever is smaller, until the family's excess is
    exhausted."

    Design: Corner/calculations/smallest_program_ratio_governs_and_excess_absorbs_largest_line_first
    """
    env = setup_env(api, rates=[dict(APPRENTICE_RATE)], with_program=PROGRAM_25)
    strict_program = build_program(api, allowed_apprentice_hours_per_100_journey=15, period_count=4)
    journeyworker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice_1 = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    apprentice_2 = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=strict_program["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date=WEEK)
    build_line(
        api, env, submission["id"], journeyworker["id"],
        **compliant_paid_line(fringe_cash_paid_cents=2000),
    )
    apprentice_line = {
        "straight_hours": 10.00,
        "overtime_hours": 0.00,
        "base_rate_paid_cents": 2500,
        "overtime_rate_paid_cents": 0,
        "fringe_cash_paid_cents": 2000,
        "reported_as_apprentice": True,
    }
    line_a1 = build_line(api, env, submission["id"], apprentice_1["id"], **apprentice_line)
    line_a2 = build_line(api, env, submission["id"], apprentice_2["id"], **apprentice_line)
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    assert float(finalized["excess_apprentice_hours"]) == 14.00
    assert float(finalized["total_hours_reported"]) == 60.00
    priced_a1 = get_success_data(api.get_payroll_line(line_a1["id"], officer_headers))
    priced_a2 = get_success_data(api.get_payroll_line(line_a2["id"], officer_headers))
    assert float(priced_a1["reclassified_journey_hours"]) == 10.00
    assert float(priced_a2["reclassified_journey_hours"]) == 4.00
    assert priced_a1["required_base_cents"] == 2500
    assert finalized["compliance_status"] == "DEFICIENT"


def test_the_overtime_factor_lifts_the_basic_rate_only(api, officer_headers):
    """Required overtime is 7500 plus 2000, not 1.5 times 7000, and the gap hides from variant A.

    PRD 3.6 step four: "The scaled overtime requirement is `required_base_cents` multiplied by
    the overtime factor of one and a half, rounded half up to a whole cent, plus
    `required_fringe_cents` added afterwards ... The fringe component is never multiplied by the
    overtime factor — that too is a pinned interpretation." PRD 3.6:
    "`straight_time_underpayment_cents` is the sum of the per-line straight-time deficiencies
    only — the preliminary screen the portal shows, which omits every overtime deficiency".

    Design: Corner/calculations/overtime_multiplier_lifts_the_basic_rate_only_not_the_fringe
    """
    env = setup_env(api, rates=ONE_RATE)
    worker_ok = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    worker_short = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date=WEEK)
    line_ok = build_line(
        api, env, submission["id"], worker_ok["id"],
        straight_hours=40.00, overtime_hours=8.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=7500, fringe_cash_paid_cents=2000,
    )
    line_short = build_line(
        api, env, submission["id"], worker_short["id"],
        straight_hours=40.00, overtime_hours=8.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=7000, fringe_cash_paid_cents=2000,
    )
    move_clock(api, WEEK)
    finalized = finalize(api, env, submission["id"])

    assert get_success_data(
        api.get_payroll_line(line_ok["id"], officer_headers)
    )["line_underpayment_cents"] == 0
    assert get_success_data(
        api.get_payroll_line(line_short["id"], officer_headers)
    )["line_underpayment_cents"] == 4000
    assert finalized["straight_time_underpayment_cents"] == 0
    assert finalized["make_whole_underpayment_cents"] == 4000
    assert float(finalized["total_hours_reported"]) == 96.00
    assert finalized["compliance_status"] == "DEFICIENT"


def test_only_accepted_weeks_credit_the_certified_hours_ledger(api, officer_headers):
    """Two certified weeks of 40.00 and 24.00 hours; only the accepted one reaches the ledger.

    PRD 2.10: "A contract assignment's `cumulative_certified_hours` must at all times equal the
    sum of `total_hours_reported` over the payroll submissions on that assignment whose
    `workflow_status` is `ACCEPTED`. Submissions in `DRAFT`, `PENDING_CERTIFICATION`,
    `SUBMITTED`, `UNDER_REVIEW` or `RETURNED` contribute nothing at all."

    Design: Corner/calculations/only_accepted_submissions_credit_the_certified_hours_ledger
    """
    env = setup_env(api, rates=ONE_RATE)
    worker_1 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    worker_2 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    week_1 = build_submission(api, env, week_ending_date="2026-07-25T00:00:00.000Z")
    build_line(
        api, env, week_1["id"], worker_1["id"], **compliant_paid_line(fringe_cash_paid_cents=2000)
    )
    week_2 = build_submission(api, env, week_ending_date=WEEK)
    build_line(
        api, env, week_2["id"], worker_2["id"],
        **compliant_paid_line(straight_hours=24.00, fringe_cash_paid_cents=2000),
    )
    move_clock(api, WEEK)
    first = finalize(api, env, week_1["id"])
    second = finalize(api, env, week_2["id"])
    certify(api, env, week_1["id"])
    certify(api, env, week_2["id"])
    get_success_data(api.begin_review_payroll_submission(week_1["id"], officer_headers))

    resp = api.accept_payroll_submission(week_1["id"], officer_headers)
    accepted = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert accepted["workflow_status"] == "ACCEPTED"
    assert float(first["total_hours_reported"]) == 40.00

    still_filed = get_success_data(api.get_payroll_submission(week_2["id"], officer_headers))
    assert still_filed["workflow_status"] == "SUBMITTED"
    assert float(second["total_hours_reported"]) == 24.00

    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 40.00


def test_a_single_critical_finding_freezes_a_project_that_owes_nothing(api, cruz_headers):
    """Step one of the posture ladder fires on the critical count before any money is consulted.

    PRD 2.9: "It is evaluated in a pinned order in which the first matching step wins. Step one:
    if the project has at least one open critical finding, the posture is `FROZEN`." PRD 3.10:
    "which means a single critical finding freezes the project outright, immediately blocking
    further payroll work on every tier of it."

    Design: Corner/calculations/a_single_critical_finding_freezes_a_project_owing_nothing
    """
    env, submission, rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    certify(api, env, submission["id"])
    assert get_success_data(api.get_project(env["project"]["id"], cruz_headers))["posture"] == "OPEN"

    resp = api.create_finding(
        {
            "project_id": env["project"]["id"],
            "payroll_submission_id": submission["id"],
            "worker_id": rows[0]["worker_id"],
            "finding_type": "MISSING_PAYROLL",
            "severity": "CRITICAL",
            "restitution_required_cents": 0,
        },
        cruz_headers,
    )
    finding = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert finding["status"] == "OPEN"
    assert finding["restitution_outstanding_cents"] == 0

    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_critical_finding_count"] == 1
    assert project["open_finding_count"] == 1
    assert project["outstanding_restitution_cents"] == 0
    assert project["posture"] == "FROZEN"
    contractor = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert contractor["debarment_risk_score"] == 40
    assert contractor["debarment_status"] == "CLEAR"


def test_the_second_open_finding_restricts_the_project_at_exactly_two(api, cruz_headers):
    """One open MINOR leaves the project OPEN; the second takes the count to 2 and RESTRICTED.

    PRD 2.9: "Step three: otherwise, if the project's open finding count is two or more, the
    posture is `RESTRICTED`; exactly two open findings does restrict." PRD 3.11: "Each such
    finding whose `severity` is `CRITICAL`
    contributes forty points, each `MAJOR` fifteen points, and each `MINOR` eight points."

    Design: Corner/calculations/the_second_open_finding_restricts_the_project_at_exactly_two
    """
    env, submission, _rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    certify(api, env, submission["id"])
    build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="MISCLASSIFICATION", severity="MINOR", restitution_required_cents=0,
    )
    assert get_success_data(api.get_project(env["project"]["id"], cruz_headers))["posture"] == "OPEN"

    resp = api.create_finding(
        {
            "project_id": env["project"]["id"],
            "payroll_submission_id": submission["id"],
            "finding_type": "MISCLASSIFICATION",
            "severity": "MINOR",
            "restitution_required_cents": 0,
        },
        cruz_headers,
    )
    second = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert second["worker_id"] is None

    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 2
    assert project["open_critical_finding_count"] == 0
    assert project["outstanding_restitution_cents"] == 0
    assert project["posture"] == "RESTRICTED"
    contractor = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert contractor["debarment_risk_score"] == 16
    assert contractor["debarment_status"] == "CLEAR"


def test_risk_decay_lands_only_when_a_whole_twenty_eight_day_period_closes(api, cruz_headers):
    """At 27 days elapsed the score is still 40; one millisecond later it drops to 35.

    PRD 3.11: "otherwise it is five points for each complete four-week period — each full 28
    days — that has elapsed between `last_finding_at` and the current logical clock instant, with
    any partial period discarded rather than rounded up." PRD 2.5: "the decay-period count inside
    that score is taken by discarding any fractional period rather than rounding it."

    Design: Corner/calculations/risk_decay_lands_only_when_a_whole_twenty_eight_day_period_closes
    """
    env, submission, _rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    certify(api, env, submission["id"])
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="MISSING_PAYROLL", severity="CRITICAL", restitution_required_cents=0,
    )
    contractor = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert contractor["last_finding_at"] == WEEK
    assert contractor["debarment_risk_score"] == 40

    move_clock(api, "2026-08-28T23:59:59.999Z")
    assert get_success_data(
        api.get_contractor(env["contractor"]["id"], cruz_headers)
    )["debarment_risk_score"] == 40

    move_clock(api, "2026-08-29T00:00:00.000Z")
    decayed = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert decayed["debarment_risk_score"] == 35
    assert decayed["debarment_status"] == "CLEAR"
    assert get_success_data(api.get_finding(finding["id"], cruz_headers))["status"] == "OPEN"
    assert get_success_data(
        api.get_project(env["project"]["id"], cruz_headers)
    )["posture"] == "FROZEN"


def test_certifying_at_the_exact_portal_deadline_is_not_late(api, officer_headers):
    """Week 08-01 with cutoff 10 days and no grace is due 08-11, and 08-11 exactly is on time.

    PRD 3.7: "A submission's `filing_due_at` is its `week_ending_date` advanced by the portal's
    `cutoff_offset_days` whole days and then by the portal's `grace_hours` hours." PRD 3.7: "A
    successful signing writes `certified_by_staff_id` with the acting staff row's identifier,
    sets `statement_signed_at` and `submitted_at` to the current logical clock instant ... and
    sets `is_late` to true exactly when `submitted_at` falls strictly after `filing_due_at`. A
    submission transmitted at the deadline instant precisely is on time, not late."

    Design: Corner/calculations/certifying_at_the_exact_portal_deadline_is_not_late
    """
    env, submission, _rows = setup_finalized_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
        portal_overrides={"cutoff_offset_days": 10, "grace_hours": 0},
    )
    assert submission["filing_due_at"] == "2026-08-11T00:00:00.000Z"

    move_clock(api, "2026-08-11T00:00:00.000Z")
    resp = api.certify_payroll_submission(submission["id"], env["certifier_headers"], {})
    signed = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert signed["workflow_status"] == "SUBMITTED"
    assert signed["filing_due_at"] == "2026-08-11T00:00:00.000Z"
    assert signed["submitted_at"] == "2026-08-11T00:00:00.000Z"
    assert signed["is_late"] is False
    assert signed["certified_by_staff_id"] == env["certifier"]["id"]

    read_back = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert read_back["is_late"] is False
