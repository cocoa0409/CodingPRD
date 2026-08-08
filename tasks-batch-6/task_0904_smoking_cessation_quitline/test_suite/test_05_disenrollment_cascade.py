"""Disenrollment cascade, completion branch, budget conservation, terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_active_with_children, setup_seven_day_achieved,
    setup_active_enrollment, create_quit_attempt, record_follow_up,
    read_program, read_enrollment, create_referral,
)
from test_helpers import factories as F

PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


def _awards(api, enrollment_id):
    resp = api.list_incentive_awards(enrollment_id, CM)
    body = resp.json()
    return body["data"]


def _referrals(api, enrollment_id):
    resp = api.list_referrals(enrollment_id, CM)
    return resp.json()["data"]


def test_disenroll_active_cascades_children(api):
    """PRD §3.8: "Disenrolling an `ACTIVE` enrollment (`ACTIVE` to `DISENROLLED`)
    triggers a full cascade: every quit attempt in `COMMITTED`, `QUIT_ACHIEVED`, or
    `RELAPSED` is abandoned to `ABANDONED`; ... In parallel, every coaching call in
    `SCHEDULED` is canceled to `CANCELED` (releasing the coach slot), every NRT
    shipment in `REQUESTED`, `APPROVED`, or `SHIPPED` is canceled to `CANCELED`
    (restoring remaining courses for non-delivered rows), and every referral in
    `OPEN` is closed to `CLOSED`."

    Design: Difficulty/non_linear_state_machine/enrollment_branch_disenroll_divergent_side_effects
    """
    ctx = setup_active_with_children(api)
    enr = validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    assert enr["status"] == "DISENROLLED"
    # Read the quit attempt / call / referral back through their list endpoints.
    quit_attempts = api.list_quit_attempts(ctx["enrollment_id"], CM).json()["data"]
    assert quit_attempts[0]["status"] == "ABANDONED"
    calls = api.list_coaching_calls(ctx["enrollment_id"], CM).json()["data"]
    assert calls[0]["status"] == "CANCELED"
    refs = _referrals(api, ctx["enrollment_id"])
    assert refs[0]["status"] == "CLOSED"


def test_completion_branch_pays_awards_and_closes_referral(api):
    """PRD §3.7: "That same thirty-day success drives the enrollment from `ACTIVE` to
    `COMPLETED`: every `EARNED` award on the enrollment moves to `PAID` (the amounts
    stay committed, so `incentive_earned_cents` is unchanged), and every `OPEN`
    referral is closed to `CLOSED`."

    Design: Difficulty/non_linear_state_machine/enrollment_branch_disenroll_divergent_side_effects
    """
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    create_referral(api, ctx["enrollment_id"], F.create_referral_payload(), CM)
    set_clock(api, "2026-07-02T00:00:00Z")
    record_follow_up(api, ctx["enrollment_id"], 30, True)
    enr = read_enrollment(api, ctx["enrollment_id"])
    assert enr["status"] == "COMPLETED"
    awards = _awards(api, ctx["enrollment_id"])
    assert all(a["status"] == "PAID" for a in awards), [a["status"] for a in awards]
    refs = _referrals(api, ctx["enrollment_id"])
    assert refs[0]["status"] == "CLOSED"


def test_disenroll_forfeits_awards_and_credits_budget(api):
    """PRD §3.8: "each such abandonment forfeits the enrollment's `EARNED` awards
    whose `milestone_type` is `QUIT_DATE_SET`, `SEVEN_DAY_ABSTINENT`, or
    `THIRTY_DAY_ABSTINENT`, moving each to `FORFEITED`; each forfeiture credits the
    sponsor's `budget_remaining_cents` by that award's `amount_cents` and increments
    the program's `version`."
    PRD §2.9: "Each enrollment also exposes `incentive_earned_cents`, the sum of
    `amount_cents` over its own awards in `EARNED` or `PAID` status".

    Design: Difficulty/transitive_cascade/disenroll_forfeits_awards_credits_budget_depth4
    """
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    enr = validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    assert enr["status"] == "DISENROLLED"
    quit_attempts = api.list_quit_attempts(ctx["enrollment_id"], CM).json()["data"]
    assert quit_attempts[0]["status"] == "ABANDONED"
    assert enr["incentive_earned_cents"] == 1000
    program = read_program(api, ctx["program_id"])
    assert program["budget_remaining_cents"] == 99000


def test_disenroll_forfeits_only_quit_and_abstinence_awards(api):
    """PRD §3.8: "each such abandonment forfeits the enrollment's `EARNED` awards
    whose `milestone_type` is `QUIT_DATE_SET`, `SEVEN_DAY_ABSTINENT`, or
    `THIRTY_DAY_ABSTINENT`, moving each to `FORFEITED`".

    Design: Difficulty/transitive_cascade/disenroll_forfeits_awards_credits_budget_depth4
    """
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    api.disenroll_enrollment(ctx["enrollment_id"], CM)
    awards = {a["milestone_type"]: a["status"] for a in _awards(api, ctx["enrollment_id"])}
    assert awards["QUIT_DATE_SET"] == "FORFEITED"
    assert awards["SEVEN_DAY_ABSTINENT"] == "FORFEITED"
    assert awards["ENROLLMENT"] == "EARNED"


def test_budget_conserved_after_forfeit(api):
    """PRD §2.9: "The remaining budget equals the total minus the sum of
    `amount_cents` across every `IncentiveAward` in `EARNED` or `PAID` status that
    belongs to any enrollment of a participant sponsored by that program."

    Design: Difficulty/compensating_invariant/incentive_budget_conserved_on_forfeit
    """
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    api.disenroll_enrollment(ctx["enrollment_id"], CM)
    program = read_program(api, ctx["program_id"])
    enr = read_enrollment(api, ctx["enrollment_id"])
    assert program["budget_remaining_cents"] == 99000
    assert enr["incentive_earned_cents"] == 1000
    assert program["budget_remaining_cents"] + enr["incentive_earned_cents"] == 100000


def test_budget_conservation_invariant_holds_before_and_after(api):
    """PRD §2.9: "The remaining budget equals the total minus the sum of
    `amount_cents` across every `IncentiveAward` in `EARNED` or `PAID` status that
    belongs to any enrollment of a participant sponsored by that program."

    Design: Difficulty/compensating_invariant/incentive_budget_conserved_on_forfeit
    """
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    program_before = read_program(api, ctx["program_id"])
    enr_before = read_enrollment(api, ctx["enrollment_id"])
    total = program_before["budget_total_cents"]
    assert program_before["budget_remaining_cents"] + enr_before["incentive_earned_cents"] == total
    assert program_before["budget_remaining_cents"] == 95000
    api.disenroll_enrollment(ctx["enrollment_id"], CM)
    program_after = read_program(api, ctx["program_id"])
    enr_after = read_enrollment(api, ctx["enrollment_id"])
    assert program_after["budget_remaining_cents"] + enr_after["incentive_earned_cents"] == total


def test_disenroll_from_terminal_returns_invalid_state(api):
    """PRD §2.5: "State admissibility — the target resource is in a state that admits
    the requested transition, and enrollment-scoped operations require the enrollment
    to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE` (409)."

    Design: Corner/state_machines/disenroll_from_terminal_returns_invalid_state
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False)
    validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    resp = api.disenroll_enrollment(ctx["enrollment_id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
