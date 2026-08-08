"""Service authorization creation, cost share, completion, and the budget boundary.

Difficulty queue (§1.8): combinatorial_formula / cost_share_tiered_offset_mode_a;
boundary_precision_check / budget_exact_equality_approves.
Corner queue (§1.9): authorization defaults, reverse lookup, completion, budget-over.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_plan_development_case, setup_services_active_case,
    request_authorization, approve_authorization, request_and_approve_authorization,
    get_case_version, create_authorization_payload, api_client,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


# ─── Difficulty: tiered cost share with comparable-benefit offset (mode a) ──

def test_cost_share_tiered_offset_consumer_share(api):
    """PRD §3.5: "First it derives the net cost as the greater of zero and
    `authorized_amount_cents` minus `comparable_benefit_cents`, applying the
    comparable-benefits offset before any cost share."
    PRD §3.5: "income above that but at or below 400,000 cents (4,000 dollars)
    carries 10% ... The `consumer_share_cents` is the lesser of the net cost and the
    net cost multiplied by the rate rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/cost_share_tiered_offset_mode_a
    """
    ctx = setup_plan_development_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    auth = request_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    assert auth["consumer_share_cents"] == 40000


def test_cost_share_tiered_offset_agency_share(api):
    """PRD §3.5: "The `agency_share_cents` is the net cost minus
    `consumer_share_cents`."

    Design: Difficulty/combinatorial_formula/cost_share_tiered_offset_mode_a
    """
    ctx = setup_plan_development_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    auth = request_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    assert auth["agency_share_cents"] == 360000


# ─── Difficulty: budget boundary (agency_share == funds_available) ────

def test_budget_exact_equality_approves(api):
    """PRD §3.6: "The budget check rejects with `ERR_BUDGET_EXCEEDED` when the
    authorization's `agency_share_cents` exceeds the case's current
    `funds_available_cents`."

    Design: Difficulty/boundary_precision_check/budget_exact_equality_approves
    """
    ctx = setup_services_active_case(budget_allocated_cents=360000, monthly_income_cents=150000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=360000, comparable_benefit_cents=0)
    assert approved["status"] == "APPROVED"
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_available_cents"] == 0


def test_budget_exact_equality_commits_full_agency_share(api):
    """PRD §3.6: "the case's `funds_committed_cents` rises by `agency_share_cents` and
    its `funds_available_cents` falls by the same amount, incrementing the case's
    `version`."

    Design: Difficulty/boundary_precision_check/budget_exact_equality_approves
    """
    ctx = setup_services_active_case(budget_allocated_cents=360000, monthly_income_cents=150000)
    request_and_approve_authorization(ctx, authorized_amount_cents=360000, comparable_benefit_cents=0)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_committed_cents"] == 360000


# ─── Corner: authorization creation/read/completion + budget-over ────

def test_authorization_comparable_benefit_defaults_zero(api):
    """PRD §3.5: "and optionally a `comparable_benefit_cents` offset (defaulting to
    0)."

    Design: Corner/entities/authorization_comparable_benefit_defaults_zero
    """
    ctx = setup_plan_development_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    payload = create_authorization_payload(ctx["case_id"], ctx["ipe_id"], ctx["provider_id"],
                                           authorized_amount_cents=100000)
    del payload["comparable_benefit_cents"]
    auth = validate_success(api.create_authorization(payload, ctx["counselor_headers"]), 201)
    assert auth["comparable_benefit_cents"] == 0
    assert auth["agency_share_cents"] == 100000
    assert auth["consumer_share_cents"] == 0


def test_authorizations_reverse_lookup_by_case_id(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/endpoints/authorizations_reverse_lookup_by_case_id
    """
    ctx = setup_plan_development_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    auth = request_authorization(ctx, authorized_amount_cents=100000)
    res = api.list_authorizations(ctx["counselor_headers"], params={"case_id": ctx["case_id"]})
    assert res.status_code == 200
    body = res.json()
    assert body["response_type"] == "array"
    ids = [row["id"] for row in body["data"]]
    assert auth["id"] in ids
    match = next(row for row in body["data"] if row["id"] == auth["id"])
    assert match["case_id"] == ctx["case_id"]


def test_provider_completes_own_authorization(api):
    """PRD §3.6: "The provider reports delivery on its own `APPROVED` authorization
    (ownership compares `provider_id` to `X-User-ID`, else `ERR_FORBIDDEN`), moving
    it to `COMPLETED`; the committed funds remain obligated until paid."

    Design: Corner/state_machines/provider_completes_own_authorization
    """
    ctx = setup_services_active_case()
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=100000)
    completed = validate_success(api.complete_authorization(approved["id"], ctx["provider_headers"]), 200)
    assert completed["status"] == "COMPLETED"


def test_budget_exceeded_over_by_one_cent(api):
    """PRD §3.6: "The budget check rejects with `ERR_BUDGET_EXCEEDED` when the
    authorization's `agency_share_cents` exceeds the case's current
    `funds_available_cents`."

    Design: Corner/validations/budget_exceeded_over_by_one_cent
    """
    ctx = setup_services_active_case(budget_allocated_cents=360000, monthly_income_cents=150000)
    auth = request_authorization(ctx, authorized_amount_cents=360001, comparable_benefit_cents=0)
    version = get_case_version(ctx["case_id"])
    res = api.approve_authorization(auth["id"], {"expected_case_version": version}, ctx["supervisor_headers"])
    validate_error(res, "ERR_BUDGET_EXCEEDED")
