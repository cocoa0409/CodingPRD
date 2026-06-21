"""Authentication, role authorization, and entity-backed ownership (PRD §2.1).

Translates queue B (Corner) instances from the `rbac` section.
"""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS, build_user_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import make_respondent_headers, make_mediator_headers

CLERK = TEST_USERS["clerk_headers"]


def test_missing_headers_returns_401(api):
    """PRD §2.1: "If either header is missing, or the role is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_401
    """
    resp = api.create_case(
        F.case_payload(caption="No Auth"), {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_petitioner_cannot_open_case_forbidden(api):
    """PRD §2.1: "When a request is authenticated but the acting role is not permitted
    to perform the requested operation ... the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/api/cases` | Open a new divorce case | Clerk".

    Design: Corner/rbac/petitioner_cannot_open_case_forbidden
    """
    resp = api.create_case(
        F.case_payload(caption="Wrong Role"), build_user_headers("u-pet", "Petitioner"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_mediator_cannot_enter_court_order_forbidden(api):
    """PRD §4: "POST | `/api/court-orders/{id}/enter` | Enter an order; final judgment
    supersedes the temporary order | Judge".
    PRD §2.1: "the acting role is not permitted to perform the requested operation ...
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/mediator_cannot_enter_court_order_forbidden
    """
    ctx = FX.setup_default_awaiting_judgment_final_only()
    resp = api.enter_court_order(
        ctx["final_order"]["id"], {}, make_mediator_headers("u-med"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_respondent_cannot_submit_other_partys_disclosure_forbidden(api):
    """PRD §3.3: "The acting party must own the disclosure — the `X-User-ID` must equal
    the `user_id` of the `Party` named by `party_id` — otherwise the submission is
    forbidden."

    Design: Corner/rbac/respondent_cannot_submit_other_partys_disclosure_forbidden
    """
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000)
    case, pet = ctx["case"], ctx["pet"]
    fd = FX.create_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                              gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                              mandatory_retirement_cents=0, health_insurance_cents=0)
    # Respondent (u-res) attempts to submit the petitioner-owned disclosure.
    resp = api.submit_financial_disclosure(fd["id"], make_respondent_headers("u-res"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_proposer_cannot_agree_own_plan_proposal_forbidden(api):
    """PRD §3.4: "A plan may be disputed or agreed by the case party who did *not*
    propose the current version — the acting party's identity must differ from
    `proposed_by_party_id`; if the acting party is the proposer, the action is rejected
    with `ERR_NOT_DISPUTING_PARTY` (HTTP 403)."

    Design: Corner/rbac/not_disputing_party_cannot_agree_own_proposal
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet = ctx["case"], ctx["pet"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    # Petitioner proposed; petitioner cannot agree to its own proposal.
    from test_helpers import make_petitioner_headers
    resp = api.agree_parenting_plan(plan["id"], make_petitioner_headers("u-pet"))
    validate_error(resp, ApiErrorId.ERR_NOT_DISPUTING_PARTY.value)
