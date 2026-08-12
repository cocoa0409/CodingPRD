"""Color-match workflow: the PROPOSED -> REVISION_REQUESTED -> PROPOSED cycle
and terminal lockdown of ABANDONED requests (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_color_match_request,
    assert_tint_formula,
    create_match_request,
    make_contractor_headers,
    propose_match,
    setup_account_job_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]


def test_revision_cycle_approves_second_proposal(api):
    """PRD §3.4: "Either proposal creates a new tint formula on the request's
    product with `source` `COLOR_MATCH`, `status` `ACTIVE`, and the same
    supersede semantics as library creation (any prior `ACTIVE` formula for
    the pair is retired with the supersedes link); the request's `formula_id`
    is set to the new formula and `iteration_count` increments by 1." PRD
    §3.4: "Approving moves the request to the terminal `APPROVED` and leaves
    the proposed formula `ACTIVE` and orderable."

    After a SUBMITTED -> PROPOSED -> REVISION_REQUESTED -> PROPOSED cycle, a
    second approval lands the request in APPROVED with iteration_count 2 and
    the second formula ACTIVE.

    Design: Difficulty/non_linear_state_machine/color_match_revision_cycle_loops
    """
    account, _, _, product = setup_account_job_product(
        company_name="Match Co", credit_limit_cents=1_000_000,
        jurisdiction_code="CA-OPEN", sku="P-CM", product_name="Match Base",
        tintable=True)
    cmr = create_match_request(account["id"], product["id"], sample_reference="S-1")
    first = propose_match(cmr["id"], color_code="SW 7008", name="Alabaster-ish",
                          ounces_128ths=24)
    f1 = first["formula_id"]
    owner = make_contractor_headers(account["id"])
    validate_success(api.request_match_revision(cmr["id"], owner))
    second = propose_match(cmr["id"], color_code="SW 7008", name="Alabaster v2",
                           ounces_128ths=32)
    f2 = second["formula_id"]
    resp = api.approve_match_request(cmr["id"], owner)
    approved = validate_success(resp, expected_status=200)
    assert_color_match_request(approved)
    assert approved["status"] == "APPROVED", (
        f"request must reach terminal APPROVED, got {approved['status']}")
    assert approved["iteration_count"] == 2, (
        f"each proposal increments iteration_count, got {approved['iteration_count']}")
    formula2 = validate_success(api.get_tint_formula(f2, ASSOCIATE))
    assert_tint_formula(formula2)
    assert formula2["status"] == "ACTIVE", (
        "approval leaves the proposed formula ACTIVE and orderable")
    assert formula2["revision"] == 2, (
        f"second formula of the pair takes revision 2, got {formula2['revision']}")
    assert formula2["source"] == "COLOR_MATCH"


def test_revision_request_retires_withdrawn_formula(api):
    """PRD §3.4: "Requesting a revision moves `PROPOSED` to
    `REVISION_REQUESTED`, retiring the formula referenced by `formula_id` —
    the rejected proposal is withdrawn — but only while `iteration_count` is
    still below 3 (the match-iteration cap); a revision request at the cap is
    rejected with `ERR_MATCH_ITERATION_EXHAUSTED` (HTTP 422)."

    The first proposal's formula is RETIRED the moment the revision is
    requested.

    Design: Difficulty/non_linear_state_machine/color_match_revision_cycle_loops
    """
    account, _, _, product = setup_account_job_product(
        company_name="Match Co", credit_limit_cents=1_000_000,
        jurisdiction_code="CA-OPEN", sku="P-CM", product_name="Match Base",
        tintable=True)
    cmr = create_match_request(account["id"], product["id"], sample_reference="S-1")
    first = propose_match(cmr["id"], color_code="SW 7008", name="Alabaster-ish",
                          ounces_128ths=24)
    f1 = first["formula_id"]
    owner = make_contractor_headers(account["id"])
    resp = api.request_match_revision(cmr["id"], owner)
    revised = validate_success(resp, expected_status=200)
    assert revised["status"] == "REVISION_REQUESTED"
    formula1 = validate_success(api.get_tint_formula(f1, ASSOCIATE))
    assert formula1["status"] == "RETIRED", (
        f"the rejected proposal is withdrawn: formula must be RETIRED, "
        f"got {formula1['status']}")


def _setup_abandoned_request(api):
    """A match request abandoned from SUBMITTED by the associate."""
    account, _, _, product = setup_account_job_product(
        company_name="Term Co", credit_limit_cents=1_000,
        jurisdiction_code="OR-TERM", sku="P-TERM", product_name="Base",
        tintable=True)
    cmr = create_match_request(account["id"], product["id"], sample_reference="S-9")
    resp = api.abandon_match_request(cmr["id"], ASSOCIATE)
    abandoned = validate_success(resp, expected_status=200)
    assert abandoned["status"] == "ABANDONED"
    return account, cmr


def test_proposal_on_abandoned_request_rejected(api):
    """PRD §3.4: "Either the associate or the owning contractor may abandon
    the request from `SUBMITTED`, `PROPOSED`, or `REVISION_REQUESTED`, moving
    it to the terminal `ABANDONED`". PRD §2.8: "Any state-machine precondition
    without a dedicated code — a submit not from `DRAFT`, a proposal not from
    `SUBMITTED` or `REVISION_REQUESTED`, ... — is rejected with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/abandoned_match_rejects_all_actions
    """
    _, cmr = _setup_abandoned_request(api)
    resp = api.create_match_proposal(
        cmr["id"],
        {"color_code": "SW 7009", "name": "X",
         "shots": [{"colorant_code": "B1", "ounces_128ths": 8}]},
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_color_match_request(cmr["id"], ASSOCIATE))
    assert after["status"] == "ABANDONED", (
        f"the terminal state must not move, got {after['status']}")


def test_approve_on_abandoned_request_rejected(api):
    """PRD §3.4: "An approve or revision request aimed at a request not in
    `PROPOSED` is rejected with `ERR_MATCH_NOT_REVIEWABLE` (HTTP 409), and
    that state check fires before the iteration cap is examined."

    Design: Corner/state_machines/abandoned_match_rejects_all_actions
    """
    account, cmr = _setup_abandoned_request(api)
    resp = api.approve_match_request(
        cmr["id"], make_contractor_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_REVIEWABLE)
    after = validate_success(api.get_color_match_request(cmr["id"], ASSOCIATE))
    assert after["status"] == "ABANDONED", (
        f"the terminal state must not move, got {after['status']}")
