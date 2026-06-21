"""State-machine behaviour: the agreement suspend/reinstate cycle and its branch
to CANCELLED, invalid transitions, terminal lockdown, the milestone-attainment
resubmit cycle, and program / journeyworker transition preconditions.

Covers non_linear_state_machine (agreement), and the state_machines corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_sponsor,
    create_journeyworker,
    create_qualified_journeyworker,
    create_apprentice,
    create_draft_program,
    create_active_program,
    create_draft_agreement,
    create_active_agreement,
    setup_active_agreement,
    register_agreement,
    log_ojt_entry,
    submit_attainment,
    AGENCY,
    COORD,
    WAGE_LADDER_4,
)
from test_helpers.test_users import make_sponsor_headers


# ===========================================================================
# Difficulty: non_linear_state_machine / agreement_suspend_reinstate_cycle_and_branch
# ===========================================================================
def test_agreement_suspend_then_reinstate_returns_to_active(api):
    """PRD §3.3: "the sponsor suspends an active agreement, moving `ACTIVE ->
    SUSPENDED` (the agreement must be `ACTIVE`, otherwise `ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD §3.3: "The sponsor reinstates a suspended agreement, moving `SUSPENDED ->
    ACTIVE` (the agreement must be `SUSPENDED`, otherwise `ERR_AGREEMENT_NOT_SUSPENDED`)."

    The ACTIVE->SUSPENDED->ACTIVE round trip is observable: after reinstate the
    status is ACTIVE again.

    Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_and_branch
    """
    sc = setup_active_agreement()
    headers = make_sponsor_headers(sc.sponsor_id)
    suspended = validate_success(api.suspend_agreement(sc.agreement_id, headers))
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_agreement(sc.agreement_id, headers))
    assert reinstated["status"] == "ACTIVE", f"reinstate must return to ACTIVE, got {reinstated['status']}"


def test_agreement_active_branches_to_cancelled(api):
    """PRD §3.3: "A `Sponsor` may cancel an agreement that is in `REGISTERED`,
    `ACTIVE`, or `SUSPENDED`; from any of those three states the agreement moves
    to `CANCELLED` (any other state yields `ERR_AGREEMENT_NOT_CANCELLABLE`)."

    After the suspend/reinstate cycle the ACTIVE agreement can branch to CANCELLED.

    Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_and_branch
    """
    sc = setup_active_agreement()
    headers = make_sponsor_headers(sc.sponsor_id)
    validate_success(api.suspend_agreement(sc.agreement_id, headers))
    validate_success(api.reinstate_agreement(sc.agreement_id, headers))
    cancelled = validate_success(api.cancel_agreement(sc.agreement_id, headers))
    assert cancelled["status"] == "CANCELLED", f"final state must be CANCELLED, got {cancelled['status']}"


# ===========================================================================
# Corner: state_machines / agreement_initial_state_is_draft
# ===========================================================================
def test_new_agreement_starts_in_draft(api):
    """PRD §3.3: "On creation the agreement begins in `DRAFT` with
    `current_wage_step` at 1, `ojt_hours_completed` at 0, `rti_hours_completed`
    at 0, and `milestones_attained_count` at 0."

    A freshly created agreement is in the declared initial state DRAFT.

    Design: Corner/state_machines/agreement_initial_state_is_draft
    """
    sponsor = create_sponsor()
    jw = create_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_draft_program(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    assert agr["status"] == "DRAFT", f"new agreement must be DRAFT, got {agr['status']}"


# ===========================================================================
# Corner: state_machines / activate_agreement_from_draft_invalid_returns_not_registered
# ===========================================================================
def test_activate_draft_agreement_rejected_not_registered(api):
    """PRD §3.3: "A registered agreement is moved into training by the sponsor,
    advancing `REGISTERED -> ACTIVE`; this requires the agreement to be
    `REGISTERED` (otherwise `ERR_AGREEMENT_NOT_REGISTERED`)."

    Activating a DRAFT (never-registered) agreement is an illegal transition.

    Design: Corner/state_machines/activate_agreement_from_draft_invalid_returns_not_registered
    """
    sponsor = create_sponsor()
    jw = create_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_draft_program(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    res = api.activate_agreement(agr["id"], make_sponsor_headers(sponsor["id"]))
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_REGISTERED.value)


# ===========================================================================
# Corner: state_machines / archive_program_with_open_agreements_rejected
# ===========================================================================
def test_archive_program_with_open_agreement_rejected(api):
    """PRD §3.1: "archiving requires the program to be `ACTIVE` (otherwise
    `ERR_PROGRAM_NOT_ACTIVE`) and requires that no agreement for the program is
    currently in `REGISTERED`, `ACTIVE`, or `SUSPENDED` (otherwise
    `ERR_PROGRAM_HAS_OPEN_AGREEMENTS`)."

    Design: Corner/state_machines/archive_program_with_open_agreements_rejected
    """
    sc = setup_active_agreement()  # leaves one ACTIVE agreement open
    res = api.archive_program(sc.program_id, AGENCY)
    validate_error(res, ApiErrorId.ERR_PROGRAM_HAS_OPEN_AGREEMENTS.value)


# ===========================================================================
# Corner: state_machines / program_activate_without_base_wage_step_rejected
# ===========================================================================
def test_activate_program_without_base_wage_step_rejected(api):
    """PRD §3.1: "Activation is refused unless the program is in `DRAFT` (otherwise
    `ERR_PROGRAM_NOT_DRAFT`), at least one wage step exists (otherwise
    `ERR_NO_WAGE_STEPS`), and among those steps there is one whose
    `ojt_hours_threshold` is exactly zero - the entry-level base step (otherwise
    `ERR_NO_BASE_WAGE_STEP`)."

    A program whose only step has threshold 8 (no threshold-0 base) is refused.

    Design: Corner/state_machines/program_activate_without_base_wage_step_rejected
    """
    sponsor = create_sponsor()
    program = create_draft_program(sponsor["id"], wage_ladder=[(2, 8, 0.65)])
    res = api.activate_program(program["id"], AGENCY)
    validate_error(res, ApiErrorId.ERR_NO_BASE_WAGE_STEP.value)


# ===========================================================================
# Corner: state_machines / deactivate_journeyworker_with_apprentices_rejected
# ===========================================================================
def test_deactivate_journeyworker_with_apprentices_rejected(api):
    """PRD §3.2: "From `QUALIFIED`, deactivation requires the worker to be
    `QUALIFIED` (otherwise `ERR_JOURNEYWORKER_NOT_QUALIFIED`) and requires
    `active_apprentice_count` to be zero (otherwise
    `ERR_JOURNEYWORKER_HAS_APPRENTICES`); on success the status becomes `INACTIVE`."

    A QUALIFIED journeyworker supervising a registered agreement cannot be
    deactivated.

    Design: Corner/state_machines/deactivate_journeyworker_with_apprentices_rejected
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    register_agreement(sponsor["id"], agr["id"], program["version"])
    res = api.deactivate_journeyworker(jw["id"], make_sponsor_headers(sponsor["id"]))
    validate_error(res, ApiErrorId.ERR_JOURNEYWORKER_HAS_APPRENTICES.value)


# ===========================================================================
# Corner: state_machines / attainment_resubmit_after_reject_then_approve
# ===========================================================================
def test_attainment_resubmit_after_reject_then_approve(api):
    """PRD §3.6: "A rejected attainment is not the end of the road: the sponsor
    resubmits it, moving `REJECTED -> SUBMITTED` (the attainment must be
    `REJECTED`, otherwise `ERR_ATTAINMENT_NOT_REJECTED`), reopening the
    adjudication cycle."
    PRD §3.6: "Approval moves an attainment `SUBMITTED -> APPROVED`, requiring the
    attainment to be `SUBMITTED` (otherwise `ERR_ATTAINMENT_NOT_SUBMITTED`) and
    the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`)."

    Reject -> resubmit (->SUBMITTED) -> approve (->APPROVED) exercises the return
    arc and bumps milestones_attained_count to 1.

    Design: Corner/state_machines/attainment_resubmit_after_reject_then_approve
    """
    sc = setup_active_agreement(completion_type="COMPETENCY_BASED", milestones=[{}])
    milestones = get_success_data(
        api.list_milestones(make_sponsor_headers(sc.sponsor_id), params={"program_id": sc.program_id})
    )
    att = submit_attainment(sc.sponsor_id, sc.agreement_id, milestones[0]["id"])
    validate_success(api.reject_milestone_attainment(att["id"], COORD))
    resubmitted = validate_success(api.resubmit_milestone_attainment(att["id"], make_sponsor_headers(sc.sponsor_id)))
    assert resubmitted["status"] == "SUBMITTED"
    approved = validate_success(api.approve_milestone_attainment(att["id"], COORD))
    assert approved["status"] == "APPROVED"
    agr = get_success_data(api.get_agreement(sc.agreement_id, make_sponsor_headers(sc.sponsor_id)))
    assert agr["milestones_attained_count"] == 1


# ===========================================================================
# Corner: state_machines / terminal_rejected_ojt_cannot_be_approved
# ===========================================================================
def test_rejected_ojt_entry_cannot_be_approved(api):
    """PRD §3.4: "Approval moves an entry `PENDING -> APPROVED` and requires the
    entry to be `PENDING` (otherwise `ERR_OJT_ENTRY_NOT_PENDING`) and, as a
    cross-entity guard, requires the parent agreement to be `ACTIVE` (otherwise
    `ERR_AGREEMENT_NOT_ACTIVE`)."

    A REJECTED entry is terminal and cannot be approved.

    Design: Corner/state_machines/terminal_rejected_ojt_cannot_be_approved
    """
    sc = setup_active_agreement()
    entry = log_ojt_entry(sc.sponsor_id, sc.agreement_id, 480, 600, 2)
    validate_success(api.reject_ojt_entry(entry["id"], COORD))
    res = api.approve_ojt_entry(entry["id"], COORD)
    validate_error(res, ApiErrorId.ERR_OJT_ENTRY_NOT_PENDING.value)
