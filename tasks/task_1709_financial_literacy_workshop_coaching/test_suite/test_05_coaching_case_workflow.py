"""Coaching-case branching state machine: revert loop, hold/resume cycle,
completion fork, invalid transitions, plan gating, one-open-case rule, and
goal-plan OCC (PRD §3.4, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_case,
    create_certified_coach,
    create_coaching_case_payload,
    create_goal_plan_for_case,
    create_goal_plan_payload,
    create_participant,
    create_snapshot,
    get_success_data,
    setup_case_with_draft_plan,
    transition_case,
    validate_error,
    validate_success,
)


def _case_with_snapshot(api, admin_headers):
    """Certified coach + participant + INTAKE case + one outcome snapshot."""
    coach = create_certified_coach(admin_headers)
    participant = create_participant(admin_headers)
    case = create_case(participant["id"], coach["id"], admin_headers,
                       intake_date="2026-08-01")
    create_snapshot(participant["id"], "2026-08-01T00:00:00Z", admin_headers,
                    credit_score=600)
    return coach, participant, case


def test_case_plan_draft_revert_loop_leaves_plan_draft(api, admin_headers):
    """PRD §3.4: "`PLAN_DRAFT` → `INTAKE`: the revision loop; any existing
    `DRAFT` goal plans simply remain `DRAFT`."

    Design: Difficulty/non_linear_state_machine/coaching_case_branching_revert_and_hold_cycles
    """
    _coach, _participant, case = _case_with_snapshot(api, admin_headers)
    case = transition_case(case["id"], "PLAN_DRAFT", admin_headers)
    plan = create_goal_plan_for_case(case["id"], case["version"], admin_headers)
    reverted = transition_case(case["id"], "INTAKE", admin_headers)
    assert reverted["status"] == "INTAKE"
    plan_after = validate_success(api.get_goal_plan(plan["id"], admin_headers))
    assert plan_after["status"] == "DRAFT", (
        "revision loop must leave the existing DRAFT plan untouched"
    )


def test_case_hold_resume_and_completion_drive_plan_states(api, admin_headers):
    """PRD §3.4: "`PLAN_ACTIVE` → `ON_HOLD`: the case's `ACTIVE` goal plan
    freezes to `FROZEN`". PRD §3.4: "`ON_HOLD` → `PLAN_ACTIVE`: requires the
    assigned coach to be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`); the case's
    `FROZEN` plan returns to `ACTIVE`". PRD §3.4: "`PLAN_ACTIVE` → `COMPLETED`:
    requires at least one outcome snapshot to exist for the participant
    (`ERR_OUTCOME_REQUIRED`); the case's `ACTIVE` plan transitions to
    `ACHIEVED`."

    Design: Difficulty/non_linear_state_machine/coaching_case_branching_revert_and_hold_cycles
    """
    _coach, _participant, case = _case_with_snapshot(api, admin_headers)
    case = transition_case(case["id"], "PLAN_DRAFT", admin_headers)
    plan = create_goal_plan_for_case(case["id"], case["version"], admin_headers)
    case = transition_case(case["id"], "PLAN_ACTIVE", admin_headers)
    assert case["status"] == "PLAN_ACTIVE"
    assert get_success_data(api.get_goal_plan(plan["id"], admin_headers))["status"] == "ACTIVE"

    transition_case(case["id"], "ON_HOLD", admin_headers)
    assert get_success_data(api.get_goal_plan(plan["id"], admin_headers))["status"] == "FROZEN"

    transition_case(case["id"], "PLAN_ACTIVE", admin_headers)
    assert get_success_data(api.get_goal_plan(plan["id"], admin_headers))["status"] == "ACTIVE"

    completed = transition_case(case["id"], "COMPLETED", admin_headers)
    assert completed["status"] == "COMPLETED"
    assert get_success_data(api.get_goal_plan(plan["id"], admin_headers))["status"] == "ACHIEVED"


def test_case_intake_to_plan_active_rejected(api, admin_headers):
    """PRD §3.4: "A target that is not reachable from the case's current state
    is rejected with `ERR_INVALID_TRANSITION`".

    Design: Corner/state_machines/case_intake_to_plan_active_rejected
    """
    coach = create_certified_coach(admin_headers, full_name="CIV", email="civ@test.org")
    participant = create_participant(admin_headers, full_name="PIV", email="piv@test.org")
    case = create_case(participant["id"], coach["id"], admin_headers,
                       intake_date="2026-08-01")
    resp = api.transition_coaching_case(
        case["id"], {"target_state": "PLAN_ACTIVE"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_plan_activation_without_draft_plan_rejected(api, admin_headers):
    """PRD §3.4: "`PLAN_DRAFT` → `PLAN_ACTIVE`: requires a goal plan for the
    case in `DRAFT` status to exist (`ERR_PLAN_REQUIRED`)".

    Design: Corner/validations/plan_activation_without_draft_plan_rejected
    """
    coach = create_certified_coach(admin_headers, full_name="CPR", email="cpr@test.org")
    participant = create_participant(admin_headers, full_name="PPR", email="ppr@test.org")
    case = create_case(participant["id"], coach["id"], admin_headers,
                       intake_date="2026-08-01")
    transition_case(case["id"], "PLAN_DRAFT", admin_headers)
    resp = api.transition_coaching_case(
        case["id"], {"target_state": "PLAN_ACTIVE"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_REQUIRED)


def test_second_open_case_rejected(api, admin_headers):
    """PRD §3.4: "the participant must not already hold a case in any
    non-terminal status — `INTAKE`, `PLAN_DRAFT`, `PLAN_ACTIVE`, `ON_HOLD`, or
    `PLAN_STALLED` (`ERR_OPEN_CASE_EXISTS`)".

    Design: Corner/validations/second_open_case_rejected
    """
    coach = create_certified_coach(admin_headers, full_name="COC", email="coc@test.org")
    participant = create_participant(admin_headers, full_name="POC", email="poc@test.org")
    create_case(participant["id"], coach["id"], admin_headers, intake_date="2026-08-01")
    resp = api.create_coaching_case(
        create_coaching_case_payload(participant["id"], coach["id"],
                                     intake_date="2026-08-02"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_CASE_EXISTS)


def test_occ_goal_plan_stale_version_returns_412(api, admin_headers):
    """PRD §2.8: "Creating a goal plan requires `expected_case_version`,
    carrying the client's last observed `version` of the parent coaching case.
    If the case's version has advanced since that observation — for example
    because another plan was created against it, or a transition moved it —
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)". PRD §2.8:
    "Successful goal-plan creation itself increments the parent case's
    `version` by 1".

    Design: Corner/cross_cutting_layers/occ_goal_plan_stale_version_returns_412
    """
    coach = create_certified_coach(admin_headers, full_name="COCC", email="cocc@test.org")
    participant = create_participant(admin_headers, full_name="POCC", email="pocc@test.org")
    case = create_case(participant["id"], coach["id"], admin_headers,
                       intake_date="2026-08-01")
    case = transition_case(case["id"], "PLAN_DRAFT", admin_headers)
    observed_version = case["version"]

    plan1 = validate_success(
        api.create_goal_plan(
            create_goal_plan_payload(case["id"], observed_version),
            admin_headers,
        ),
        expected_status=201,
    )
    assert plan1["status"] == "DRAFT"

    # Replaying the pre-create version is stale: the first create bumped it.
    resp = api.create_goal_plan(
        create_goal_plan_payload(case["id"], observed_version,
                                 monthly_savings_goal_cents=30000,
                                 credit_score_target=700),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # The losing request superseded nothing: plan 1 is still the only DRAFT.
    plan1_after = validate_success(api.get_goal_plan(plan1["id"], admin_headers))
    assert plan1_after["status"] == "DRAFT"
