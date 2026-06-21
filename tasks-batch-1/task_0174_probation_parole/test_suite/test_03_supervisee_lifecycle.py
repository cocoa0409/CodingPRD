"""Supervisee lifecycle: the revocation/abscond cycle, activation preconditions,
and revoke cascade onto conditions.

Difficulty queue: non_linear_state_machine (revocation cycle).
Corner queue: state_machines (activate-without-adopted, revoke cascade).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_officer_headers, make_judge_headers,
    create_officer, open_supervisee, add_draft_assessment, adopt_assessment,
    setup_active_supervisee, add_active_condition,
)


# ─── Difficulty: non_linear_state_machine / supervisee_revocation_cycle ───
def test_abscond_then_return_to_supervision_rebounds_to_active(api):
    """PRD §3.7: "When the supervisee resurfaces, an Officer returns the case to
    supervision, permitted only when the supervisee is ABSCONDED; this rebound
    moves the supervisee back from ABSCONDED to ACTIVE"

    ACTIVE -> ABSCONDED -> ACTIVE is a cycle back to ACTIVE, not a one-way pipe.

    Design: Difficulty/non_linear_state_machine/supervisee_revocation_cycle_absconded_rebound
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    validate_success(api.abscond_supervisee(sup["id"], oh), 200)
    returned = validate_success(api.return_to_supervision(sup["id"], oh), 200)
    assert returned["status"] == "ACTIVE"


def test_abscond_autofiles_abscond_violation_not_dismissed_on_return(api):
    """PRD §3.7: "Absconding moves the supervisee from ACTIVE to ABSCONDED and, as
    the first link of the abscond cascade, auto-creates a Violation of class
    ABSCOND filed by the acting officer ... in FILED status"
    PRD §3.7: "it deliberately does not dismiss the outstanding abscond violation,
    which remains for separate adjudication."

    After abscond+return, exactly the FILED ABSCOND violation persists — the loop
    leaves a side effect that distinguishes it from a no-op pipeline.

    Design: Difficulty/non_linear_state_machine/supervisee_revocation_cycle_absconded_rebound
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    validate_success(api.abscond_supervisee(sup["id"], oh), 200)
    validate_success(api.return_to_supervision(sup["id"], oh), 200)

    vios, _ = validate_paginated(
        api.list_violations(sup["id"], oh, params={"status": "FILED"})
    )
    abscond_vios = [v for v in vios if v["violation_class"] == "ABSCOND"]
    assert len(abscond_vios) == 1
    assert abscond_vios[0]["status"] == "FILED"


# ─── Corner: state_machines / activate_supervisee_without_adopted_assessment ──
def test_activate_without_adopted_assessment_rejected(api):
    """PRD §3.1: "activation is permitted only when the supervisee is in INTAKE and
    at least one risk assessment for the supervisee has already been adopted ...
    activation while no assessment has been adopted is likewise refused on the
    same ground."

    Design: Corner/state_machines/activate_supervisee_without_adopted_assessment_invalid_state
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    # Only a DRAFT (un-adopted) assessment exists.
    add_draft_assessment(sup["id"], officer["id"], total=10)
    res = api.activate_supervisee(sup["id"], oh)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert after["status"] == "INTAKE"


# ─── Corner: state_machines / revoke_cascades_conditions_to_suspended ───
def test_revoke_cascades_active_conditions_to_suspended(api):
    """PRD §3.7: "A SupervisingJudge may revoke a REVOCATION_PENDING case, which is
    terminal: it moves the supervisee to REVOKED, freezes the ledger, cascades all
    of the supervisee's PROPOSED and ACTIVE conditions to SUSPENDED"

    Design: Corner/state_machines/revoke_cascades_conditions_to_suspended
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    cond = add_active_condition(
        sup["id"], officer["id"],
        condition_type="CURFEW", minimum_level_required="ADMINISTRATIVE",
    )
    assert cond["status"] == "ACTIVE"

    # Reach REVOCATION_PENDING via the abscond path (no point threshold needed).
    validate_success(api.abscond_supervisee(sup["id"], oh), 200)
    validate_success(api.refer_revocation(sup["id"], oh), 200)
    revoked = validate_success(api.revoke_supervisee(sup["id"], make_judge_headers()), 200)
    assert revoked["status"] == "REVOKED"

    cond_after = validate_success(api.get_condition(sup["id"], cond["id"], oh), 200)
    assert cond_after["status"] == "SUSPENDED"
