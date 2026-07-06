"""Transitive cascades: PWD supersession reverting PERM and voiding steps
(depth-3), and PERM denial cascading to I-140 denial (depth-2) (PRD §3.2, §3.3).

Queue A / Difficulty — rule `transitive_cascade`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    create_employer, create_issued_pwd, create_pending_pwd, create_perm_case,
    add_recruitment_step, issue_pwd, setup_filed_perm_case, create_beneficiary,
    create_i140_petition, make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]


def _recruiting_case_with_step_and_pending_superseder():
    """PWD_A issued, a RECRUITING PermCase on PWD_A with one ACTIVE JOB_ORDER
    step, and PWD_B (same employer/soc/area) still PENDING."""
    emp = create_employer()
    pwd_a = create_issued_pwd(emp["id"])
    pc = create_perm_case(emp["id"], pwd_a["id"])
    hdr = make_employer_agent_headers(emp["id"])
    pc = validate_success(api_client.transition_perm_case(pc["id"], {"to_status": "RECRUITING"}, hdr), 200)
    step = add_recruitment_step(emp["id"], pc["id"], step_type="JOB_ORDER",
                                start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    pwd_b = create_pending_pwd(emp["id"])  # same soc_code/area_code as PWD_A
    return emp, pwd_a, pc, step, pwd_b


def test_pwd_supersede_reverts_dependent_perm_case_to_draft(api):
    """PRD §3.2: "Issuance then supersedes competition: any other determination for
    the same combination of `employer_id`, `soc_code`, and `area_code` that is
    currently `ISSUED` transitions from `ISSUED` to `SUPERSEDED`."
    PRD §3.2: "Every `PermCase` whose `pwd_id` points at the now-superseded
    determination and whose `status` is `DRAFT`, `RECRUITING`, or `QUIET_PERIOD`
    is reverted to `DRAFT`."

    Design: Difficulty/transitive_cascade/pwd_supersede_reverts_perm_and_voids_steps
    """
    emp, pwd_a, pc, step, pwd_b = _recruiting_case_with_step_and_pending_superseder()
    issue_pwd(emp["id"], pwd_b["id"])  # supersedes PWD_A, cascades
    assert validate_success(api.get_pwd(pwd_a["id"], DOL), 200)["status"] == "SUPERSEDED"
    assert validate_success(api.get_perm_case(pc["id"], DOL), 200)["status"] == "DRAFT"


def test_pwd_supersede_voids_active_recruitment_steps(api):
    """PRD §3.3: "If it was `RECRUITING`, every `ACTIVE` `RecruitmentStep` on the
    case is voided (moved from `ACTIVE` to `VOID`) and `recruitment_start` is
    cleared."

    Design: Difficulty/transitive_cascade/pwd_supersede_reverts_perm_and_voids_steps
    """
    emp, pwd_a, pc, step, pwd_b = _recruiting_case_with_step_and_pending_superseder()
    issue_pwd(emp["id"], pwd_b["id"])
    assert validate_success(api.get_recruitment_step(step["id"], DOL), 200)["status"] == "VOID"


def test_perm_denial_marks_case_denied(api):
    """PRD §3.3: "From either `FILED` or `AUDIT`, a `DOLAnalyst` reaches a terminal
    outcome: certifying the case to `CERTIFIED`, or denying it to `DENIED`."

    Design: Difficulty/transitive_cascade/perm_deny_cascades_i140_deny
    """
    employer, pwd, pc = setup_filed_perm_case()
    ben = create_beneficiary(employer["id"])
    create_i140_petition(employer["id"], ben["id"], category="EB2", perm_case_id=pc["id"])
    denied = validate_success(api.transition_perm_case(pc["id"], {"to_status": "DENIED"}, DOL), 200)
    assert denied["status"] == "DENIED"


def test_perm_denial_cascades_draft_i140_to_denied(api):
    """PRD §3.3: "Denial from `FILED` or from `AUDIT` cascades downstream: every
    `I140Petition` whose `perm_case_id` points at this case and whose `status` is
    `DRAFT` or `SUBMITTED` is transitioned to `DENIED`."

    Design: Difficulty/transitive_cascade/perm_deny_cascades_i140_deny
    """
    employer, pwd, pc = setup_filed_perm_case()
    ben = create_beneficiary(employer["id"])
    i140 = create_i140_petition(employer["id"], ben["id"], category="EB2", perm_case_id=pc["id"])
    validate_success(api.transition_perm_case(pc["id"], {"to_status": "DENIED"}, DOL), 200)
    assert validate_success(api.get_i140_petition(i140["id"], DOL), 200)["status"] == "DENIED"
