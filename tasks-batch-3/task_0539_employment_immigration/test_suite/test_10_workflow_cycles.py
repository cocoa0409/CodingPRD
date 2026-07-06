"""Non-linear state machines: the H-1B RFE cycle and the PERM audit cycle
(PRD §3.6, §3.3).

Queue A / Difficulty — rule `non_linear_state_machine`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    setup_submitted_h1b_petition, issue_rfe, setup_filed_perm_case,
    make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]


def test_rfe_response_returns_petition_to_submitted(api):
    """PRD §3.6: "The employer answers by moving the petition back from
    `RFE_ISSUED` to `SUBMITTED`, permitted only from `RFE_ISSUED` and only while
    the current clock is at or before `rfe_due_date` (otherwise `ERR_RFE_EXPIRED`);
    a successful response sets `rfe_status` to `RESPONDED` and stamps
    `rfe_response_date` to the current clock."

    Design: Difficulty/non_linear_state_machine/h1b_petition_rfe_cycle
    """
    ctx = setup_submitted_h1b_petition()
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    issue_rfe(ctx["petition"]["id"])
    responded = validate_success(
        api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr), 200)
    assert responded["status"] == "SUBMITTED"
    assert responded["rfe_status"] == "RESPONDED"


def test_second_rfe_reenters_rfe_issued_proving_cycle(api):
    """PRD §3.6: "A `USCISOfficer` may issue a Request for Evidence on a submitted
    petition, moving it from `SUBMITTED` to `RFE_ISSUED` (defined only from
    `SUBMITTED`)."
    PRD §3.6: "This `SUBMITTED` ⇄ `RFE_ISSUED` loop may repeat."

    Design: Difficulty/non_linear_state_machine/h1b_petition_rfe_cycle
    """
    ctx = setup_submitted_h1b_petition()
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    issue_rfe(ctx["petition"]["id"])
    validate_success(api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr), 200)
    second = validate_success(
        api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "RFE_ISSUED"}, USCIS), 200)
    assert second["status"] == "RFE_ISSUED"


def test_audit_response_returns_perm_case_to_filed(api):
    """PRD §3.3: "A `DOLAnalyst` moves it from `FILED` to `AUDIT` (permitted only
    from `FILED`). The employer answers the audit, and an `EmployerAgent` moves it
    back from `AUDIT` to `FILED` (permitted only from `AUDIT`)."

    Design: Difficulty/non_linear_state_machine/perm_case_audit_cycle
    """
    employer, pwd, pc = setup_filed_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    validate_success(api.transition_perm_case(pc["id"], {"to_status": "AUDIT"}, DOL), 200)
    back = validate_success(api.transition_perm_case(pc["id"], {"to_status": "FILED"}, hdr), 200)
    assert back["status"] == "FILED"


def test_second_audit_reenters_audit_proving_cycle(api):
    """PRD §3.3: "This `FILED` ⇄ `AUDIT` loop may repeat."

    Design: Difficulty/non_linear_state_machine/perm_case_audit_cycle
    """
    employer, pwd, pc = setup_filed_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    validate_success(api.transition_perm_case(pc["id"], {"to_status": "AUDIT"}, DOL), 200)
    validate_success(api.transition_perm_case(pc["id"], {"to_status": "FILED"}, hdr), 200)
    second = validate_success(api.transition_perm_case(pc["id"], {"to_status": "AUDIT"}, DOL), 200)
    assert second["status"] == "AUDIT"
