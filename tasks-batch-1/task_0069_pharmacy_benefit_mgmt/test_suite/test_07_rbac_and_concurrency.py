"""RBAC, authentication, optimistic concurrency, and FK reverse-listing
(PRD §2.1, §2.6, §3.7). Corner queue: rbac, cross_cutting_complexity_layers, endpoints.
"""
from test_helpers import fixtures as fx, validate_error, validate_paginated, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers import build_user_headers, make_director_headers, make_reviewer_headers


# ─── Corner / rbac.pharmacy_provider_cannot_create_plan ─────────────────────
def test_pharmacy_provider_cannot_create_plan(api):
    """PRD §2.1: "the write operations are partitioned exclusively as described above."
    PRD §2.1: "When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/pharmacy_provider_cannot_create_plan
    """
    resp = api_client.create_plan(
        {"name": "P", "plan_year": 2026, "deductible_cents": 0, "oop_max_cents": 200000,
         "tier_copay_cents": {"TIER_1": 1000, "TIER_2": 3500, "TIER_3": 7000, "SPECIALTY": 25000}},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ─── Corner / rbac.reviewer_cannot_decide_pa ────────────────────────────────
def test_reviewer_cannot_decide_pa(api):
    """PRD §2.1: "A `PharmacistReviewer` intakes prior-authorization requests and appeals denied authorizations, but is never permitted to decide an authorization."

    Design: Corner/rbac/reviewer_cannot_decide_pa
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    resp = api_client.decide_prior_authorization(
        pa["id"],
        {"decision": "APPROVE", "expected_prior_authorization_version": pa["version"]},
        make_reviewer_headers("U_REV"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ─── Corner / rbac.missing_auth_headers_returns_unauthenticated ─────────────
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.list_plans({"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Corner / cross_cutting.occ_stale_plan_version_on_finalize_rejected ─────
def test_finalize_rebates_stale_plan_version_rejected(api):
    """PRD §2.6: "Running the rebate-finalization sweep against a benefit plan requires
    the request body to carry `expected_benefit_plan_version`, holding the client's last
    observed `version` of the plan."
    PRD §2.6: "the sweep is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
    finalization against a stale rebate basis."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_finalize_rejected
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    stale_version = plan["version"]
    fx.archive_plan(plan["id"])  # bumps version to 2
    resp = api_client.finalize_rebates(
        plan["id"], {"expected_benefit_plan_version": stale_version}, fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── Corner / cross_cutting.occ_version_increments_on_pa_decide ─────────────
def test_pa_decide_increments_version_by_one(api):
    """PRD §2.4: "an integer `version` that begins at 1 on creation and increments by
    one on every mutation of the resource."
    PRD §3.3: "Approving an authorization moves it from `PENDING_REVIEW` to `APPROVED`
    (or from `APPEALED` to `APPROVED`), records the deciding director in
    `decided_by_user_id`, sets `approved_quantity_remaining` equal to `authorized_fills`,
    and increments the authorization's version."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_pa_decide
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    assert pa["version"] == 1
    approved = fx.decide_pa(pa["id"], "APPROVE", pa["version"], decider_id="U_DIR")
    assert approved["status"] == "APPROVED"
    assert approved["version"] == 2, approved["version"]


# ─── Corner / endpoints.fk_reverse_list_claims_by_member ────────────────────
def test_list_claims_by_member(api):
    """PRD §4: "GET | `/pbm/claims` | List claims"
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/fk_reverse_list_claims_by_member
    """
    fx.set_clock("2026-08-12T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="T1", drug_name="T1", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    resp = api_client.list_claims(fx.PROVIDER, params={"member_id": m["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]


# ─── Corner / calculations.rebate_30day_provisional_accrual_value ───────────
def test_rebate_30day_provisional_accrual_value(api):
    """PRD §3.7: "computes `accrued_cents` on a 30-day-equivalent basis: a 30-day fill counts as one fill and accrues the drug's `rebate_per_fill_cents` once"
    PRD §3.7: "A new accrual is created in `PROVISIONAL` status with `clawback_cents` of 0, and the originating claim's independent `rebate_status` dimension is set to `ACCRUED`."

    Design: Corner/calculations/rebate_30day_provisional_accrual_value
    """
    fx.set_clock("2026-07-12T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    fx.create_rebate_agreement(plan["id"])
    drug = fx.create_drug(plan["id"], ndc="RB", drug_name="RB", tier="TIER_1",
                          ingredient_cost_cents=10000, rebate_per_fill_cents=4000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["rebate_status"] == "ACCRUED"
    accrual = fx.get_accrual_for_claim(claim["id"])
    assert accrual["accrued_cents"] == 4000, accrual["accrued_cents"]
    assert accrual["status"] == "PROVISIONAL", accrual["status"]


# ─── Corner / endpoints.fk_reverse_list_accruals_by_claim ───────────────────
def test_list_accruals_by_claim(api):
    """PRD §4: "GET | `/pbm/rebate-accruals` | List rebate accruals"
    PRD §3.7: "The accrual records the `claim_id` of the paying claim and the `rebate_agreement_id` of the crediting agreement"

    Design: Corner/endpoints/fk_reverse_list_accruals_by_claim
    """
    fx.set_clock("2026-08-14T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    fx.create_rebate_agreement(plan["id"])
    drug = fx.create_drug(plan["id"], ndc="RB", drug_name="RB", tier="TIER_1",
                          ingredient_cost_cents=10000, rebate_per_fill_cents=4000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    resp = api_client.list_rebate_accruals(fx.ADMIN, params={"claim_id": claim["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, meta["total_count"]
