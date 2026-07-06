"""Cross-entity state dependencies: H-1B submit requires a CERTIFIED LCA, and
I-140 submit requires a CERTIFIED PERM case (PRD §3.6, §3.7).

Queue A / Difficulty — rule `cross_entity_state_dependency`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_draft_h1b_petition, setup_filed_perm_case, create_beneficiary,
    create_i140_petition, make_employer_agent_headers,
)


def test_h1b_submit_blocked_when_lca_not_certified(api):
    """PRD §3.6: "Submission enforces three cross-entity gates: the referenced
    application must be `CERTIFIED` (otherwise `ERR_LCA_NOT_CERTIFIED`), the
    referenced registration must be `SELECTED` (otherwise
    `ERR_REGISTRATION_NOT_SELECTED`), and the `worksite_area` must be one of the
    application's `worksite_areas` (otherwise `ERR_WORKSITE_NOT_COVERED`)."

    Design: Difficulty/cross_entity_state_dependency/h1b_submit_requires_lca_certified
    """
    ctx = setup_draft_h1b_petition(lca_certified=False, run_the_lottery=True)
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    res = api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    validate_error(res, ApiErrorId.ERR_LCA_NOT_CERTIFIED, expected_status=409)


def test_h1b_submit_blocked_leaves_petition_draft(api):
    """PRD §3.6: "Filing the petition moves it from `DRAFT` to `SUBMITTED`,
    performed by an `EmployerAgent` and defined only from `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/h1b_submit_requires_lca_certified
    """
    ctx = setup_draft_h1b_petition(lca_certified=False, run_the_lottery=True)
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    assert validate_success(api.get_h1b_petition(ctx["petition"]["id"], hdr), 200)["status"] == "DRAFT"


def test_i140_submit_blocked_when_perm_not_certified(api):
    """PRD §3.7: "When `perm_case_id` is not null, the referenced PERM case must be
    `CERTIFIED`, otherwise the submission is rejected with
    `ERR_PERM_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/i140_submit_requires_perm_certified
    """
    employer, pwd, pc = setup_filed_perm_case()  # FILED, not CERTIFIED
    ben = create_beneficiary(employer["id"])
    i140 = create_i140_petition(employer["id"], ben["id"], category="EB2", perm_case_id=pc["id"])
    hdr = make_employer_agent_headers(employer["id"])
    res = api.transition_i140_petition(i140["id"], {"to_status": "SUBMITTED"}, hdr)
    validate_error(res, ApiErrorId.ERR_PERM_NOT_CERTIFIED, expected_status=409)


def test_i140_submit_blocked_leaves_petition_draft(api):
    """PRD §3.7: "Submission moves the petition from `DRAFT` to `SUBMITTED`,
    performed by an `EmployerAgent` and defined only from `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/i140_submit_requires_perm_certified
    """
    employer, pwd, pc = setup_filed_perm_case()
    ben = create_beneficiary(employer["id"])
    i140 = create_i140_petition(employer["id"], ben["id"], category="EB2", perm_case_id=pc["id"])
    hdr = make_employer_agent_headers(employer["id"])
    api.transition_i140_petition(i140["id"], {"to_status": "SUBMITTED"}, hdr)
    assert validate_success(api.get_i140_petition(i140["id"], hdr), 200)["status"] == "DRAFT"
