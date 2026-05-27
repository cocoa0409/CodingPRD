"""Multi-hop cascade chains: depth-2 and depth-3 reconciliations triggered by
state transitions across plan, participant, contribution period, and loan.

Difficulty queue A — rule 4 (transitive_cascade).
Corner queue B — Section: cross_cutting_complexity_layers (derived-field
reconciliation after loan default).
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    get_success_data,
    set_clock,
    setup_active_plan_with_enrolled_participant,
    create_and_activate_plan,
    create_and_enroll_participant,
    create_open_contribution_period,
    close_contribution_period,
    create_pending_participant,
    create_requested_loan,
    disburse_loan,
    setup_with_disbursed_loan,
    read_plan_version,
    terminate_plan_payload,
    create_contribution_period_payload,
    create_loan_payload,
    get_participant,
    get_plan,
    get_loan,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


def _setup_terminate_scenario(api):
    """Plan ACTIVE, participant ENROLLED with one CLOSED period and one DISBURSED
    loan. yos=8 GRADED_6 -> fully vested. Returns (plan_id, participant_id,
    loan_id, expected_plan_version)."""
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="TerminateCascade", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Greg",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=10_000_000)
    close_contribution_period(cp["id"])
    loan = create_requested_loan(participant["id"], principal_cents=20_000,
                                 term_months=12, annual_interest_rate_bps=700)
    disburse_loan(loan["id"])
    v_pre = read_plan_version(plan["id"])
    return plan["id"], participant["id"], loan["id"], v_pre


# ─── Difficulty/transitive_cascade/plan_terminate_cascades_to_loan_default ──

def test_plan_terminate_cascades_to_participant_terminated_and_loan_defaulted(api):
    """PRD §3.1: "Every participant of the plan whose `enrollment_status` is
    `ENROLLED` or `SUSPENDED` is moved to `TERMINATED` (depth 2) with its own
    `version` bump. For every such terminated participant, any loan in
    `DISBURSED` status is cascaded to `DEFAULTED` (depth 3), the loan's `version`
    is bumped..."

    Design: Difficulty/transitive_cascade/plan_terminate_cascades_to_loan_default_depth_3
    """
    plan_id, participant_id, loan_id, v_pre = _setup_terminate_scenario(api)
    validate_success(api.terminate_plan(plan_id, terminate_plan_payload(v_pre), _ADMIN))
    assert get_plan(plan_id)["status"] == "TERMINATED"
    assert get_participant(participant_id)["enrollment_status"] == "TERMINATED"
    assert get_loan(loan_id)["status"] == "DEFAULTED"


def test_plan_terminate_cascade_reconciles_derived_balance_fields(api):
    """PRD §3.1: "For every such terminated participant, any loan in `DISBURSED` status is cascaded to `DEFAULTED` (depth 3), the loan's `version` is bumped, and the participant's `outstanding_loan_principal_cents` is reduced to zero as the derived-field reconciliation downstream of the loan defaults."
    PRD §3.4: "Alternatively, a default — transitioning `DISBURSED → DEFAULTED`, initiated either by a plan administrator or as a cascaded consequence of the participant being terminated — treats the unpaid principal as a deemed distribution against the participant's vested employer match: the participant's `employer_balance_cents` is reduced by the loan's prior `outstanding_principal_cents` (depth-2 cascade, employee balance unaffected), the participant's `vested_employer_balance_cents` is recomputed (depth-3 derived-field reconciliation against the new employer balance), the participant's `outstanding_loan_principal_cents` is reduced by the prior outstanding (depth-2 reconciliation), and the loan moves to `DEFAULTED` with a version bump."

    Pre-terminate employer_balance=46441, outstanding_principal=20000.
    Post-terminate employer_balance=46441-20000=26441; with yos=8 GRADED_6 full
    vesting, vested_employer_balance=26441; outstanding_loan_principal=0.

    Design: Difficulty/transitive_cascade/plan_terminate_cascades_to_loan_default_depth_3
    """
    plan_id, participant_id, _loan_id, v_pre = _setup_terminate_scenario(api)
    validate_success(api.terminate_plan(plan_id, terminate_plan_payload(v_pre), _ADMIN))
    p = get_participant(participant_id)
    assert p["outstanding_loan_principal_cents"] == 0
    assert p["employer_balance_cents"] == 26_441
    assert p["vested_employer_balance_cents"] == 26_441


# ─── Difficulty/transitive_cascade/contribution_close_cascades_to_vested ────

def test_contribution_close_updates_participant_employer_balance_depth_2(api):
    """PRD §3.3: "the participant's `employer_balance_cents` is increased by the
    period's `employer_match_cents` (depth-2 cascade)..."

    Single CLOSED period with gross=500000, deferral=400bps, TIERED match yields
    employer_match=17500; participant.employer_balance_cents = 17500.

    Design: Difficulty/transitive_cascade/contribution_close_cascades_to_vested_balance_depth_2
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Cascade", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "Henry",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    closed = validate_success(api.close_contribution_period(cp["id"], _ADMIN))
    assert closed["employer_match_cents"] == 17_500
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 17_500


def test_contribution_close_recomputes_vested_employer_balance_depth_3(api):
    """PRD §3.3: "the participant's `vested_employer_balance_cents` is recomputed
    (depth-3 derived-field reconciliation, against the new `employer_balance_cents`)..."
    PRD §2.9: "The vested employer balance is then the participant's
    `employer_balance_cents` multiplied by the vested percentage expressed as
    basis points and divided by ten thousand, with a floor applied at the
    multiplication."

    yos=2 GRADED_6 -> 40% vesting; vested_employer_balance =
    floor(17500 * 4000 / 10000) = 7000.

    Design: Difficulty/transitive_cascade/contribution_close_cascades_to_vested_balance_depth_2
    """
    _plan, participant = setup_active_plan_with_enrolled_participant(
        clock_iso="2026-06-15T00:00:00Z",
        plan_overrides={"name": "Cascade3", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "Henry3",
                               "hire_date": "2024-06-15T00:00:00Z",
                               "deferral_rate_bps": 400},
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    p = get_participant(participant["id"])
    assert p["vested_employer_balance_cents"] == 7_000


# ─── Corner/cross_cutting/derived_field_reconciliation_after_loan_default ──

def test_loan_default_reconciles_employer_vested_and_outstanding(api):
    """PRD §3.4: "Alternatively, a default — transitioning `DISBURSED → DEFAULTED`,
    initiated either by a plan administrator or as a cascaded consequence of the
    participant being terminated — treats the unpaid principal as a deemed
    distribution against the participant's vested employer match: the participant's
    `employer_balance_cents` is reduced by the loan's prior `outstanding_principal_cents`
    (depth-2 cascade, employee balance unaffected), the participant's
    `vested_employer_balance_cents` is recomputed (depth-3 derived-field
    reconciliation against the new employer balance), the participant's
    `outstanding_loan_principal_cents` is reduced by the prior outstanding
    (depth-2 reconciliation)..."

    yos=8 GRADED_6 fully vested; employer_balance=46441 pre-default;
    post-default employer_balance=46441-20000=26441, vested_employer=26441,
    outstanding_loan_principal=0.

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_loan_default
    """
    _plan, participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "DR", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        participant_overrides={
            "full_name": "Dr",
            "date_of_birth": "1980-06-15T00:00:00Z",
            "hire_date": "2018-06-15T00:00:00Z",
            "annual_compensation_cents": 50_000_000,
            "deferral_rate_bps": 400,
        },
        gross_compensation_cents=10_000_000,
        loan_principal_cents=20_000,
    )
    validate_success(api.default_loan(loan["id"], _ADMIN))
    assert get_loan(loan["id"])["status"] == "DEFAULTED"
    p = get_participant(participant["id"])
    assert p["employer_balance_cents"] == 26_441
    assert p["vested_employer_balance_cents"] == 26_441
    assert p["outstanding_loan_principal_cents"] == 0
