"""State-machine transitions: cycles, terminal lockdown, double-transition rejection,
hardship-pay debit ordering.

Difficulty queue A — rule 3 (non_linear_state_machine) cycle tests.
Corner queue B — Section: state_machines and Section: errors (ERR_INVALID_STATE
triggerability).
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_plan_payload,
    create_participant_payload,
    terminate_plan_payload,
    set_clock,
    setup_active_plan_with_enrolled_participant,
    setup_with_requested_hardship,
    create_and_activate_plan,
    create_pending_participant,
    read_plan_version,
    get_participant,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Difficulty/non_linear_state_machine ─────────────────────────────────────

def test_participant_enroll_suspend_resume_returns_to_enrolled(api):
    """PRD §3.2: "A participant may then be suspended (`ENROLLED → SUSPENDED`) and
    resumed (`SUSPENDED → ENROLLED`); resumption is also gated on the plan being
    `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/participant_enrolled_suspended_enrolled_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="P", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_pending_participant(
        plan["id"], full_name="Fred F",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    p_id = participant["id"]
    get_success_data(api.enroll_participant(p_id, _ADMIN))
    get_success_data(api.suspend_participant(p_id, _ADMIN))
    final = validate_success(api.resume_participant(p_id, _ADMIN))
    assert final["enrollment_status"] == "ENROLLED"


def test_participant_enroll_suspend_resume_advances_version_monotonically(api):
    """PRD §2.4: "The `version` field is a non-negative integer that begins at 1
    on creation and increments by exactly one with every mutation..."

    Design: Difficulty/non_linear_state_machine/participant_enrolled_suspended_enrolled_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="P2", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_pending_participant(
        plan["id"], full_name="Fred F2",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    p_id = participant["id"]
    assert participant["version"] == 1
    v_enroll = get_success_data(api.enroll_participant(p_id, _ADMIN))["version"]
    v_suspend = get_success_data(api.suspend_participant(p_id, _ADMIN))["version"]
    v_resume = get_success_data(api.resume_participant(p_id, _ADMIN))["version"]
    assert v_enroll == 2, f"After enroll, version must be 2 (1 + 1), got {v_enroll}"
    assert v_suspend == 3, f"After suspend, version must be 3, got {v_suspend}"
    assert v_resume == 4, f"After resume, version must be 4, got {v_resume}"


def test_plan_activate_freeze_unfreeze_returns_to_active(api):
    """PRD §3.1: "A live plan can be frozen by transitioning `ACTIVE → FROZEN`, and
    unfrozen back via `FROZEN → ACTIVE`; both are version-bumping mutations."

    Design: Difficulty/non_linear_state_machine/plan_active_frozen_active_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = get_success_data(api.create_plan(
        create_plan_payload(name="CyclePlan", match_formula="TIERED",
                            vesting_schedule="CLIFF_3"),
        _ADMIN,
    ))
    plan_id = plan["id"]
    get_success_data(api.activate_plan(plan_id, _ADMIN))
    get_success_data(api.freeze_plan(plan_id, _ADMIN))
    final = validate_success(api.unfreeze_plan(plan_id, _ADMIN))
    assert final["status"] == "ACTIVE"


def test_plan_activate_freeze_unfreeze_advances_version(api):
    """PRD §2.4: "The `version` field is a non-negative integer that begins at 1
    on creation and increments by exactly one with every mutation..."

    Design: Difficulty/non_linear_state_machine/plan_active_frozen_active_cycle
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = get_success_data(api.create_plan(
        create_plan_payload(name="CyclePlan2", match_formula="TIERED",
                            vesting_schedule="CLIFF_3"),
        _ADMIN,
    ))
    plan_id = plan["id"]
    assert plan["version"] == 1
    v_active = get_success_data(api.activate_plan(plan_id, _ADMIN))["version"]
    v_frozen = get_success_data(api.freeze_plan(plan_id, _ADMIN))["version"]
    v_active2 = get_success_data(api.unfreeze_plan(plan_id, _ADMIN))["version"]
    assert v_active == 2
    assert v_frozen == 3
    assert v_active2 == 4


# ─── Corner/state_machines instances ────────────────────────────────────────

def test_plan_activate_from_already_active_returns_invalid_state(api):
    """PRD §2.10: "State eligibility runs fourth; a transition attempted against
    a resource whose current state does not permit it returns `ERR_INVALID_STATE`."

    Design: Corner/state_machines/plan_activate_from_already_active_returns_invalid_state
    """
    plan = create_and_activate_plan(name="P", match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    res = api.activate_plan(plan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_plan_terminate_from_terminated_returns_invalid_state(api):
    """PRD §2.10: "State eligibility runs fourth; a transition attempted against
    a resource whose current state does not permit it returns `ERR_INVALID_STATE`."

    Design: Corner/state_machines/plan_terminate_from_terminated_returns_invalid_state
    """
    plan = create_and_activate_plan(name="P", match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    v_active = plan["version"]
    terminated = validate_success(api.terminate_plan(
        plan["id"], terminate_plan_payload(v_active), _ADMIN,
    ))
    # Second terminate on the already-TERMINATED plan
    res = api.terminate_plan(plan["id"], terminate_plan_payload(terminated["version"]), _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_double_enroll_returns_invalid_state(api):
    """PRD §2.10: "State eligibility runs fourth; a transition attempted against
    a resource whose current state does not permit it returns `ERR_INVALID_STATE`."

    Design: Corner/errors/err_invalid_state_triggerable_via_double_enroll
    """
    set_clock("2026-06-15T00:00:00Z")
    _plan, participant = setup_active_plan_with_enrolled_participant(
        plan_overrides={"name": "E1", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
        participant_overrides={"full_name": "E"},
    )
    res = api.enroll_participant(participant["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_hardship_pay_drains_employee_balance_first(api):
    """PRD §3.5: "Payment debits the participant's balances in a fixed order:
    employee deferrals first — the participant's `employee_balance_cents` is reduced
    by the approved amount, and any shortfall (the portion of the approved amount
    that exceeds the participant's employee deferrals) is then taken from the
    participant's `employer_balance_cents`."

    Design: Corner/state_machines/hardship_pay_drains_employee_balance_first
    """
    # Setup: age 45 participant with 2 closed contribution periods so
    # employee_balance=40000, employer_balance=35000, vested_employer=14000.
    # Approved hardship = 27000 cents (matches max_hardship cap). 27000 fits
    # entirely inside the 40000 employee balance, so only employee_balance is
    # debited.
    set_clock("2026-06-15T00:00:00Z")
    _plan, participant, hardship = setup_with_requested_hardship(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "HP", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={
            "full_name": "Hp",
            "date_of_birth": "1981-06-15T00:00:00Z",   # age 45 at clock
            "hire_date": "2024-06-15T00:00:00Z",       # yos=2 under GRADED_6 -> 40% vested
            "annual_compensation_cents": 12_000_000,
            "deferral_rate_bps": 400,
        },
        contribution_periods=2,
        gross_compensation_cents=500_000,
        requested_amount_cents=100_000,
        hardship_category="MEDICAL_EXPENSES",
    )
    # Approve to compute approved_amount_cents.
    approved = validate_success(api.approve_hardship(hardship["id"], _ADMIN))
    assert approved["approved_amount_cents"] == 27_000
    # Pay
    validate_success(api.pay_hardship(hardship["id"], _ADMIN))
    p = get_participant(participant["id"])
    # employee_balance reduced by full approved amount; employer_balance unchanged
    assert p["employee_balance_cents"] == 40_000 - 27_000
    assert p["employer_balance_cents"] == 35_000
