"""Transitions whose legality depends on the state of a different aggregate."""
from test_helpers import (
    ApiErrorId,
    build_submission,
    build_worker,
    get_success_data,
    make_portal_admin_headers,
    setup_env,
    setup_proposed_contractor_with_invited_tier,
    validate_error,
)

APPRENTICE_RATES = [{"fringe_hourly_rate_cents": 2000, "apprentice_scale_pct": [50, 60, 70, 80]}]
PROGRAM = {"allowed_apprentice_hours_per_100_journey": 25, "period_count": 4}


def test_tier_activation_is_blocked_by_the_contractors_debarment_standing(
    api, portal_admin_headers
):
    """A tier created while the firm was CLEAR cannot be activated once it is PROPOSED.

    PRD 3.4: "Activating a tier is a `PortalAdmin` action that moves it `INVITED → ACTIVE`.
    The tier must currently be `INVITED`; the contractor must be `CLEAR` and `REGISTERED` at
    that moment, not merely at creation time, and a firm whose standing has slipped in the
    interim is refused with `ERR_CONTRACTOR_DEBARRED`".

    Design: Difficulty/cross_entity_state_dependency/tier_activation_blocked_by_contractor_debarment_state
    """
    state = setup_proposed_contractor_with_invited_tier(api)
    assert state["contractor"]["debarment_status"] == "PROPOSED"
    before = get_success_data(
        api.get_contract_assignment(state["invited_assignment"]["id"], portal_admin_headers)
    )
    assert before["status"] == "INVITED"

    resp = api.activate_contract_assignment(
        state["invited_assignment"]["id"], portal_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_DEBARRED.value, expected_status=409)

    after = get_success_data(
        api.get_contract_assignment(state["invited_assignment"]["id"], portal_admin_headers)
    )
    assert after["status"] == "INVITED"
    project = get_success_data(api.get_project(state["p2_project"]["id"], portal_admin_headers))
    assert project["status"] == "ACTIVE"


def test_a_proposed_firm_cannot_be_brought_onto_a_new_tier_at_all(api, portal_admin_headers):
    """The same Contractor state also blocks creating a fresh tier for it.

    PRD 3.4: "Tier creation is also gated on the firm's standing: the named contractor must
    have `debarment_status` `CLEAR` and `registration_status` `REGISTERED`, and a firm that is
    `PROPOSED` or `DEBARRED`, or whose registration has gone `LAPSED`, cannot be brought onto a
    project at all — the attempt fails with `ERR_CONTRACTOR_DEBARRED`."

    Design: Difficulty/cross_entity_state_dependency/tier_activation_blocked_by_contractor_debarment_state
    """
    state = setup_proposed_contractor_with_invited_tier(api)
    assert state["contractor"]["debarment_status"] == "PROPOSED"

    resp = api.create_contract_assignment(
        state["p2_project"]["id"],
        {"contractor_id": state["contractor"]["id"], "subcontract_amount_cents": 250000},
        portal_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_DEBARRED.value, expected_status=409)


def _lapsed_program_draft(api, standing):
    """Apprentice enrolled while the program is REGISTERED, program then moved to ``standing``."""
    env = setup_env(api, rates=APPRENTICE_RATES, with_program=PROGRAM)
    apprentice = build_worker(
        api, env["contractor"]["id"], env["preparer_headers"],
        apprentice_program_id=env["program"]["id"], apprentice_period=1,
    )
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    patched = get_success_data(
        api.update_apprentice_program(
            env["program"]["id"], {"registration_status": standing}, make_portal_admin_headers()
        )
    )
    assert patched["registration_status"] == standing
    return env, submission, apprentice


def test_apprentice_line_is_blocked_by_a_lapsed_program_registration(api, portal_admin_headers):
    """The Worker's ApprenticeProgram is re-read at line-write time and refuses the line.

    PRD 3.5: "when `reported_as_apprentice` is true, three apprentice conditions are checked
    immediately: the worker's `apprentice_program_id` must resolve to a program whose
    `registration_status` is `REGISTERED`, or the line is refused with
    `ERR_APPRENTICE_PROGRAM_NOT_REGISTERED`".

    Design: Difficulty/cross_entity_state_dependency/apprentice_line_blocked_by_lapsed_program_registration
    """
    env, submission, apprentice = _lapsed_program_draft(api, "LAPSED")
    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": apprentice["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 8.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 2500,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
            "reported_as_apprentice": True,
        },
        env["preparer_headers"],
    )
    validate_error(
        resp, ApiErrorId.ERR_APPRENTICE_PROGRAM_NOT_REGISTERED.value, expected_status=422
    )

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert float(unchanged["total_hours_reported"]) == 0.00


def test_a_provisional_program_is_equally_unusable_for_an_apprentice_line(
    api, portal_admin_headers
):
    """PROVISIONAL standing does not support apprentice-rate lines either.

    PRD 3.2: "Only a program in `REGISTERED` standing supports apprentice-rate payroll lines
    — `PROVISIONAL` and `LAPSED` programs do not — and a `PortalAdmin` may move a program
    between the three standings at any time, which advances the program's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/apprentice_line_blocked_by_lapsed_program_registration
    """
    env, submission, apprentice = _lapsed_program_draft(api, "PROVISIONAL")
    resp = api.add_payroll_line(
        submission["id"],
        {
            "worker_id": apprentice["id"],
            "classification_code": "ELEC-INSIDE-JW",
            "straight_hours": 8.00,
            "overtime_hours": 0.00,
            "base_rate_paid_cents": 2500,
            "overtime_rate_paid_cents": 0,
            "fringe_cash_paid_cents": 2000,
            "reported_as_apprentice": True,
        },
        env["preparer_headers"],
    )
    validate_error(
        resp, ApiErrorId.ERR_APPRENTICE_PROGRAM_NOT_REGISTERED.value, expected_status=422
    )
    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert float(unchanged["total_hours_reported"]) == 0.00
