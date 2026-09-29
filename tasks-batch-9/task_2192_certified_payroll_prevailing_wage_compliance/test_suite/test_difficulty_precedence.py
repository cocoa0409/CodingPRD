"""Validation precedence ladder: which of two armed rules answers first."""
from test_helpers import (
    ApiErrorId,
    build_finding,
    build_line,
    build_submission,
    build_worker,
    certify,
    compliant_paid_line,
    finalize,
    get_success_data,
    move_clock,
    setup_deficient_submission_under_review,
    setup_env,
    setup_env_single_both_staff,
    validate_error,
)

APPRENTICE_RATES = [{"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}]
PROGRAM = {"allowed_apprentice_hours_per_100_journey": 25, "period_count": 4}


def _second_week_apprentice_draft(api):
    """Week 08-01 under review at 560000 short; week 08-08 a DRAFT with one apprentice line.

    Both second-week writes happen while the posture is still OPEN, because both are
    themselves posture-gated. Returns (env, week1_submission, week2_submission).
    """
    env, week1, _rows = setup_deficient_submission_under_review(
        api, rates=APPRENTICE_RATES, with_program=PROGRAM
    )
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    week2 = build_submission(api, env, week_ending_date="2026-08-08T00:00:00.000Z")
    build_line(
        api, env, week2["id"], apprentice["id"],
        straight_hours=8.00, overtime_hours=0.00,
        base_rate_paid_cents=2500, overtime_rate_paid_cents=0,
        fringe_cash_paid_cents=2000, reported_as_apprentice=True,
    )
    return env, week1, week2


def test_frozen_project_gate_answers_before_the_lapsed_program_check(api, portal_admin_headers):
    """A frozen project and a lapsed program are both armed; the state gate wins with 409.

    PRD 2.8 rung 9: "The project posture gate: the owning project's `posture` must not be
    `FROZEN` — `ERR_PROJECT_FROZEN` (HTTP 409). This rung guards five operations: opening a
    payroll submission, adding a payroll line, finalizing, certifying, and advancing a project
    to `SUBSTANTIALLY_COMPLETE`." PRD 2.8 rung 15: "Apprenticeship program registration —
    `ERR_APPRENTICE_PROGRAM_NOT_REGISTERED` (HTTP 422), on adding a payroll line and on
    finalizing." PRD 2.8: "the service reports the failure from the highest rung of the
    following ladder that the request trips, and stops there."

    Design: Difficulty/priority_pair_validation_conflict/frozen_project_state_gate_beats_lapsed_apprentice_program_referential_check
    """
    env, week1, week2 = _second_week_apprentice_draft(api)
    build_finding(
        api, env["project"]["id"], week1["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=560000,
    )
    get_success_data(
        api.update_apprentice_program(
            env["program"]["id"], {"registration_status": "LAPSED"}, portal_admin_headers
        )
    )
    # A MAJOR finding freezes on the restitution threshold without suspending the tier, so
    # the higher-priority ERR_INVALID_ASSIGNMENT_STATE rung cannot mask the pair.
    move_clock(api, "2026-08-09T00:00:00.000Z")

    resp = api.finalize_payroll_submission(week2["id"], env["preparer_headers"])
    validate_error(resp, ApiErrorId.ERR_PROJECT_FROZEN.value, expected_status=409)

    project = get_success_data(api.get_project(env["project"]["id"], portal_admin_headers))
    assert project["posture"] == "FROZEN"
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    )
    assert assignment["status"] == "ACTIVE"
    unchanged = get_success_data(api.get_payroll_submission(week2["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"


def test_the_lapsed_program_check_is_the_armed_loser_of_that_pair(api, portal_admin_headers):
    """Without the freeze the very same finalize answers ERR_APPRENTICE_PROGRAM_NOT_REGISTERED.

    PRD 3.6 step two: "A line whose `reported_as_apprentice` is true instead looks up the
    worker's enrolling program — a missing program, or one whose `registration_status` is not
    `REGISTERED`, is refused with `ERR_APPRENTICE_PROGRAM_NOT_REGISTERED`".

    Design: Difficulty/priority_pair_validation_conflict/frozen_project_state_gate_beats_lapsed_apprentice_program_referential_check
    """
    env, _week1, week2 = _second_week_apprentice_draft(api)
    get_success_data(
        api.update_apprentice_program(
            env["program"]["id"], {"registration_status": "LAPSED"}, portal_admin_headers
        )
    )
    move_clock(api, "2026-08-09T00:00:00.000Z")

    project = get_success_data(api.get_project(env["project"]["id"], portal_admin_headers))
    assert project["posture"] == "OPEN"
    resp = api.finalize_payroll_submission(week2["id"], env["preparer_headers"])
    validate_error(
        resp, ApiErrorId.ERR_APPRENTICE_PROGRAM_NOT_REGISTERED.value, expected_status=422
    )


def _over_ratio_finalized(api, env):
    """A finalized week-08-01 payroll carrying exactly 20.00 excess apprentice hours."""
    j1 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    j2 = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    for worker in (j1, j2):
        build_line(
            api, env, submission["id"], worker["id"],
            **compliant_paid_line(fringe_cash_paid_cents=2000),
        )
    build_line(
        api, env, submission["id"], apprentice["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=2500, overtime_rate_paid_cents=0,
        fringe_cash_paid_cents=2000, reported_as_apprentice=True,
    )
    return finalize(api, env, submission["id"])


def test_segregation_of_duties_answers_before_the_ratio_attestation(api, portal_admin_headers):
    """A self-certifying BOTH staff row on an over-ratio payroll answers 409, not 422.

    PRD 2.8 rung 11: "Segregation of duties on certification — `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 409), on certification only." PRD 2.8 rung 30: "The apprentice-ratio attestation —
    `ERR_APPRENTICE_RATIO_EXCEEDED` (HTTP 422), on certification." PRD 3.7:
    "The staff row signing the statement of compliance must not be the staff row named in the
    submission's `prepared_by_staff_id`. A firm whose single employee holds `capability`
    `BOTH` therefore cannot self-certify their own work: the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_apprentice_ratio_attestation_on_certify
    """
    env = setup_env_single_both_staff(api, rates=APPRENTICE_RATES, with_program=PROGRAM)
    finalized = _over_ratio_finalized(api, env)
    assert float(finalized["excess_apprentice_hours"]) == 20.00

    resp = api.certify_payroll_submission(finalized["id"], env["certifier_headers"], {})
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=409)

    after = get_success_data(api.get_payroll_submission(finalized["id"], portal_admin_headers))
    assert float(after["excess_apprentice_hours"]) == 20.00
    assert after["workflow_status"] == "PENDING_CERTIFICATION"
    assert after["certified_by_staff_id"] is None


def test_the_ratio_attestation_is_the_armed_loser_of_that_pair(api):
    """With two distinct staff rows the same over-ratio payroll answers 422 instead.

    PRD 3.7: "`apprentice_ratio_exception_note` carries the contractor's written explanation
    for exceeding the apprentice ratio; when the submission's `excess_apprentice_hours` is
    greater than zero this note must be present and non-empty, and its absence is refused
    with `ERR_APPRENTICE_RATIO_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_apprentice_ratio_attestation_on_certify
    """
    env = setup_env(api, rates=APPRENTICE_RATES, with_program=PROGRAM)
    finalized = _over_ratio_finalized(api, env)
    assert float(finalized["excess_apprentice_hours"]) == 20.00

    resp = api.certify_payroll_submission(finalized["id"], env["certifier_headers"], {})
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_RATIO_EXCEEDED.value, expected_status=422)

    # Supplying the note lets the very same filing through.
    signed = certify(
        api, env, finalized["id"],
        apprentice_ratio_exception_note="Crew shortage; JATC notified in writing.",
    )
    assert signed["workflow_status"] == "SUBMITTED"
    assert signed["certified_by_staff_id"] == env["certifier"]["id"]
