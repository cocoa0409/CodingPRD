"""State-machine transitions, cyclic loops, and invalid-transition rejections.

Translates queue A (Difficulty) rule non_linear_state_machine, plus queue B (Corner)
`state_machines` instances covering invalid transitions, the disclosure return/resubmit
loop, and the FULL_AGREEMENT precondition.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import (
    make_petitioner_headers, make_respondent_headers, make_mediator_headers,
    make_judge_headers,
)

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Rule: non_linear_state_machine — instance mediation_session_partial_then_reopen_cycle
# =========================================================================
def _setup_scheduled_session():
    """Contested CA case in MEDIATION (mediator u-med); both disclosures SUBMITTED; a
    SCHEDULED MediationSession. Returns (case, session)."""
    ctx = FX.setup_case_in_mediation(pet_gross=800000, res_gross=400000)
    case = ctx["case"]
    session = FX.schedule_session(case["id"], "u-med")
    return case, session


def test_mediation_partial_agreement_then_reopen_returns_in_session(api):
    """PRD §3.5: "An outcome of `PARTIAL_AGREEMENT` moves the session from `IN_SESSION`
    to `PARTIAL_AGREEMENT`, which is non-terminal — the same session row may be reopened
    for a further round, advancing it from `PARTIAL_AGREEMENT` back to `IN_SESSION`".

    Design: Difficulty/non_linear_state_machine/mediation_session_partial_then_reopen_cycle
    """
    case, session = _setup_scheduled_session()
    FX.start_session(session["id"], "u-med")
    FX.conclude_session(session["id"], "PARTIAL_AGREEMENT", "u-med")
    reopened = validate_success(
        api.start_mediation_session(session["id"], make_mediator_headers("u-med")), 200)
    assert reopened["status"] == "IN_SESSION"


def test_mediation_partial_agreement_is_intermediate_state(api):
    """PRD §3.5: "An outcome of `PARTIAL_AGREEMENT` moves the session from `IN_SESSION`
    to `PARTIAL_AGREEMENT`, which is non-terminal".

    Design: Difficulty/non_linear_state_machine/mediation_session_partial_then_reopen_cycle
    """
    case, session = _setup_scheduled_session()
    FX.start_session(session["id"], "u-med")
    concluded = validate_success(api.conclude_mediation_session(
        session["id"], {"outcome": "PARTIAL_AGREEMENT"}, make_mediator_headers("u-med")), 200)
    assert concluded["status"] == "PARTIAL_AGREEMENT"


# =========================================================================
# Rule: non_linear_state_machine — instance parenting_plan_revision_loop_cycle
# =========================================================================
def _setup_proposed_plan_two_parties(petitioner_overnights=200, respondent_overnights=165):
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER",
                           petitioner_overnights, respondent_overnights)
    return case, pet, res, plan


def test_parenting_plan_revision_loop_returns_to_disputed(api):
    """PRD §3.4: "A revised plan may itself be disputed again by the other party (the one
    who did not propose the revision), moving it from `REVISED` back to `DISPUTED` — this
    is the revision loop, and it may repeat across rounds."

    Petitioner proposes -> respondent disputes -> respondent revises (now proposer) ->
    petitioner disputes the revision -> DISPUTED.

    Design: Difficulty/non_linear_state_machine/parenting_plan_revision_loop_cycle
    """
    case, pet, res, plan = _setup_proposed_plan_two_parties(200, 165)
    api.dispute_parenting_plan(plan["id"], make_respondent_headers("u-res"))
    validate_success(api.revise_parenting_plan(
        plan["id"], F.revise_plan_payload(150, 215), make_respondent_headers("u-res")), 200)
    disputed = validate_success(
        api.dispute_parenting_plan(plan["id"], make_petitioner_headers("u-pet")), 200)
    assert disputed["status"] == "DISPUTED"


def test_parenting_plan_revision_updates_overnights(api):
    """PRD §3.4: "a revision supplies new `petitioner_overnights` and
    `respondent_overnights` (which must still total 365), updates those overnight values,
    reassigns `proposed_by_party_id` to the acting party, recomputes `petitioner_time_pct`,
    and moves the plan from `DISPUTED` to `REVISED`."

    After dispute + revise to 150/215, the petitioner overnights are 150.

    Design: Difficulty/non_linear_state_machine/parenting_plan_revision_loop_cycle
    """
    case, pet, res, plan = _setup_proposed_plan_two_parties(200, 165)
    api.dispute_parenting_plan(plan["id"], make_respondent_headers("u-res"))
    revised = validate_success(api.revise_parenting_plan(
        plan["id"], F.revise_plan_payload(150, 215), make_respondent_headers("u-res")), 200)
    assert revised["status"] == "REVISED"
    assert revised["petitioner_overnights"] == 150


# =========================================================================
# Queue B (Corner) — state_machines
# =========================================================================
def test_dispute_already_agreed_plan_returns_invalid_state(api):
    """PRD §3.4: "Disputing a plan advances it from `PROPOSED` to `DISPUTED`."
    PRD §2.5: "for any state-transition operation, the target resource must currently be
    in a state from which the requested transition is defined; otherwise the response is
    `ERR_INVALID_STATE` (HTTP 409)."

    AGREED has no dispute transition.

    Design: Corner/state_machines/dispute_already_agreed_plan_returns_invalid_state
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    FX.agree_plan(plan["id"], "u-res", "RESPONDENT")  # AGREED
    resp = api.dispute_parenting_plan(plan["id"], make_petitioner_headers("u-pet"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_held_hearing_returns_invalid_state(api):
    """PRD §3.8: "A judge marks a hearing held, advancing it from `SCHEDULED` to `HELD`".
    PRD §2.5: "the target resource must currently be in a state from which the requested
    transition is defined; otherwise the response is `ERR_INVALID_STATE` (HTTP 409)."

    A held hearing has no cancel transition.

    Design: Corner/state_machines/hold_hearing_then_cancel_returns_invalid_state
    """
    case = FX.create_case()
    h = validate_success(api.create_hearing(F.hearing_payload(
        case["id"], "DEPT-1", "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z"), CLERK), 201)
    validate_success(api.hold_hearing(h["id"], make_judge_headers("u-judge")), 200)
    resp = api.cancel_hearing(h["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_disclosure_return_then_resubmit_recomputes_net(api):
    """PRD §3.3: "A returned disclosure may be resubmitted: submitting it again advances
    it from `RETURNED` back to `SUBMITTED`, re-deriving `net_monthly_income_cents` from
    its current field values".

    gross 720000, deductions 120000+0+0=120000 -> net 600000 on resubmit.

    Design: Corner/state_machines/financial_disclosure_return_then_resubmit_recomputes_net
    """
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000, with_respondent=False)
    case, pet = ctx["case"], ctx["pet"]
    fd = FX.create_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                              gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                              mandatory_retirement_cents=0, health_insurance_cents=0)
    FX.submit_disclosure(fd["id"], "u-pet", "PETITIONER")
    validate_success(api.return_financial_disclosure(fd["id"], CLERK), 200)  # SUBMITTED -> RETURNED
    resubmitted = validate_success(
        api.submit_financial_disclosure(fd["id"], make_petitioner_headers("u-pet")), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["net_monthly_income_cents"] == 600000


def test_mediation_full_agreement_blocked_when_plan_not_agreed(api):
    """PRD §3.5: "An outcome of `FULL_AGREEMENT` moves the session from `IN_SESSION` to
    `FULL_AGREEMENT`, but only if the case's parenting plan is currently in `AGREED`
    status; if the plan is not agreed, the conclusion is rejected with
    `ERR_PLAN_NOT_AGREED`."

    Design: Corner/state_machines/mediation_full_agreement_blocked_when_plan_not_agreed
    """
    ctx = FX.setup_case_in_mediation(pet_gross=800000, res_gross=400000)
    case, pet = ctx["case"], ctx["pet"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)  # PROPOSED, not agreed
    session = FX.schedule_session(case["id"], "u-med")
    FX.start_session(session["id"], "u-med")
    resp = api.conclude_mediation_session(
        session["id"], {"outcome": "FULL_AGREEMENT"}, make_mediator_headers("u-med"))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_AGREED.value)
    fetched_plan = validate_success(api.get_parenting_plan(plan["id"], CLERK), 200)
    assert fetched_plan["status"] == "PROPOSED"
