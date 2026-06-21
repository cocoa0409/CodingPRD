"""Body/parameter validation rules and FK reverse-reachability listing.

Translates queue B (Corner) instances from the `validations` and `endpoints` sections.
"""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import make_petitioner_headers

CLERK = TEST_USERS["clerk_headers"]


def test_overnights_not_365_on_plan_create_returns_422(api):
    """PRD §3.4: "`petitioner_overnights` plus `respondent_overnights` must total
    exactly 365, and any proposal or revision that violates this is rejected with
    `ERR_OVERNIGHTS_NOT_365` (HTTP 422)."

    Design: Corner/validations/overnights_not_365_on_plan_create_returns_422
    """
    ctx = FX.setup_contested_discovery(pet_gross=800000, res_gross=400000)
    case, pet = ctx["case"], ctx["pet"]
    payload = F.parenting_plan_payload(case["id"], pet["id"], 100, 200)  # sum 300
    resp = api.create_parenting_plan(payload, make_petitioner_headers("u-pet"))
    validate_error(resp, ApiErrorId.ERR_OVERNIGHTS_NOT_365.value)


def test_negative_net_income_on_submit_returns_422(api):
    """PRD §3.3: "If the gross income is less than the sum of the three declared
    deductions — that is, if net income would be negative — the submission is rejected
    with `ERR_NEGATIVE_NET_INCOME` (HTTP 422)".

    gross 100000 vs deductions 50000+40000+20000=110000 -> negative net.

    Design: Corner/validations/negative_net_income_on_submit_returns_422
    """
    ctx = FX.setup_default_pending(pet_gross=100000, res_gross=400000)
    case, pet = ctx["case"], ctx["pet"]
    fd = FX.create_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                              gross_monthly_income_cents=100000, tax_withholding_cents=50000,
                              mandatory_retirement_cents=40000, health_insurance_cents=20000)
    resp = api.submit_financial_disclosure(fd["id"], make_petitioner_headers("u-pet"))
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_NET_INCOME.value)
    # Disclosure stays DRAFT (transition rejected).
    got = api.get_financial_disclosure(fd["id"], CLERK).json()["data"]
    assert got["status"] == "DRAFT"


def test_guideline_missing_for_case_state_returns_404(api):
    """PRD §3.1: "The `state_code` must match the `state_code` of an existing registered
    guideline schedule; if no such schedule exists, case creation is rejected with
    `ERR_GUIDELINE_NOT_FOUND`."

    Design: Corner/validations/guideline_missing_for_case_state_returns_404
    """
    FX.register_schedule(state_code="CA")  # only CA exists
    resp = api.create_case(F.case_payload(state_code="WY", caption="In re Marriage of GG"), CLERK)
    validate_error(resp, ApiErrorId.ERR_GUIDELINE_NOT_FOUND.value)


def test_duplicate_petition_returns_409(api):
    """PRD §3.2: "A case may have exactly one petition; a second petition is rejected
    with `ERR_DUPLICATE_PETITION`."

    Design: Corner/validations/duplicate_petition_returns_409
    """
    case, pet, petition = FX.setup_filed_case_with_petitioner()
    resp = api.create_pleading(F.pleading_payload(case["id"], "PETITION", pet["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PETITION.value)


def test_duplicate_party_role_returns_409(api):
    """PRD §3.2: "A case may hold exactly one petitioner and at most one respondent;
    attempting to add a second party in a role already present on the case is rejected
    with `ERR_DUPLICATE_PARTY_ROLE`."

    Design: Corner/validations/duplicate_party_role_returns_409
    """
    case = FX.create_case()
    FX.add_petitioner(case["id"], user_id="u-pet")
    resp = api.create_party(
        F.party_payload(case["id"], "PETITIONER", "u-pet2", full_name="Pat2"), CLERK)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARTY_ROLE.value)


def test_pagination_limit_over_max_returns_422(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a negative
    `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422)."

    Design: Corner/validations/pagination_limit_over_max_returns_422
    """
    FX.create_case()
    resp = api.list_cases(CLERK, params={"limit": 101, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_fk_reverse_list_parties_by_case(api):
    """PRD §4: "GET | `/api/parties` | List parties (filter by `case_id`)".
    PRD §3.2: "Each party is created with the `case_id` it belongs to".

    Design: Corner/endpoints/fk_reverse_list_parties_by_case
    """
    case = FX.create_case()
    FX.add_petitioner(case["id"])
    FX.add_respondent(case["id"])
    resp = api.list_parties(CLERK, params={"case_id": case["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


def test_fk_reverse_list_support_orders_by_payor(api):
    """PRD §4: "GET | `/api/support-orders` | List support orders (filter by `case_id`,
    `payor_party_id`, `payee_party_id`)".

    Design: Corner/endpoints/fk_reverse_list_support_orders_by_payor
    """
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    FX.create_support_order(case["id"], "SPOUSAL", pet["id"], res["id"], "TEMPORARY")
    resp = api.list_support_orders(CLERK, params={"payor_party_id": pet["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
