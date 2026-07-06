"""Claims: provisional/final reimbursement, cyclic resubmission, adjudication."""
import pytest
from test_helpers import (
    TEST_USERS, make_provider_headers,
    validate_success, validate_error, ApiErrorId,
    setup_authorized_case, schedule_session, complete_session,
    create_claim_payload,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


# ===========================================================================
# Dual-variant: provisional vs final diverge on budget proration  (Difficulty)
# ===========================================================================
def test_claim_provisional_vs_final_diverge_on_budget_proration(api):
    """PRD §3.8: "Finally, `provisional_cents` is the larger of zero and that
    gross minus the plan's `copay_cents`."
    PRD §3.8: "The remaining budget is the larger of zero and the contract's
    `annual_reimbursement_budget_cents` minus that spent total. The claim's
    `final_cents` is then the smaller of its `provisional_cents` and that
    remaining budget, so the final figure may be less than the provisional figure
    when the remaining budget is the binding constraint, and equal to it otherwise."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_diverge_on_budget_proration
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 2, "annual_session_cap": 10,
                            "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 15000},
        plan_overrides={"copay_cents": 2000},
        provider_overrides={"network_status": "IN_NETWORK", "specialties": ["STRESS"]},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    s2 = schedule_session(case["id"], provider["id"], "2026-03-03T10:00:00Z")
    complete_session(s1["id"], provider)
    complete_session(s2["id"], provider)
    # first claim: billed 200000 capped to base 12000, minus copay 2000 -> 10000
    claim1 = fx.submit_claim(contract["id"], s1["id"], 200000, provider)
    validate_success(api.review_claim(claim1["id"], ADMIN))
    approved1 = validate_success(api.approve_claim(claim1["id"], ADMIN))
    assert approved1["final_cents"] == 10000
    # second claim: billed 15000 capped to 12000, minus copay 2000 -> provisional 10000
    claim2 = fx.submit_claim(contract["id"], s2["id"], 15000, provider)
    assert claim2["provisional_cents"] == 10000
    validate_success(api.review_claim(claim2["id"], ADMIN))
    approved2 = validate_success(api.approve_claim(claim2["id"], ADMIN))
    # remaining budget 15000-10000=5000; final = min(10000, 5000) = 5000
    assert approved2["final_cents"] == 5000
    assert approved2["final_cents"] != approved2["provisional_cents"]


def test_claim_final_equals_provisional_when_budget_ample(api):
    """PRD §3.8: "The claim's `final_cents` is then the smaller of its
    `provisional_cents` and that remaining budget, so the final figure may be less
    than the provisional figure when the remaining budget is the binding
    constraint, and equal to it otherwise."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_diverge_on_budget_proration
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 1_000_000},
        plan_overrides={"copay_cents": 2000})
    claim = fx.submit_claim(contract["id"], session["id"], 12000, provider)
    assert claim["provisional_cents"] == 10000
    validate_success(api.review_claim(claim["id"], ADMIN))
    approved = validate_success(api.approve_claim(claim["id"], ADMIN))
    # ample budget -> final equals provisional
    assert approved["final_cents"] == 10000


# ===========================================================================
# Combinatorial: order-dependent budget consumption  (Difficulty)
# ===========================================================================
def test_claim_final_order_dependent_budget_consumption(api):
    """PRD §3.8: "It sums the `final_cents` of all claims of the same contract that
    are already in `APPROVED` or `PAID` status, processed in ascending
    `created_at` order and excluding the claim now being approved, to find how
    much budget is already spent."

    Design: Difficulty/combinatorial_formula/claim_final_order_dependent_budget_consumption
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 2, "annual_session_cap": 10,
                            "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 24000},
        plan_overrides={"copay_cents": 0},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    s2 = schedule_session(case["id"], provider["id"], "2026-03-03T10:00:00Z")
    complete_session(s1["id"], provider)
    complete_session(s2["id"], provider)
    # each provisional capped to base 12000 (billed 70000 -> 12000, copay 0)
    claim1 = fx.submit_claim(contract["id"], s1["id"], 70000, provider)
    claim2 = fx.submit_claim(contract["id"], s2["id"], 70000, provider)
    validate_success(api.review_claim(claim1["id"], ADMIN))
    approved1 = validate_success(api.approve_claim(claim1["id"], ADMIN))
    assert approved1["final_cents"] == 12000
    validate_success(api.review_claim(claim2["id"], ADMIN))
    approved2 = validate_success(api.approve_claim(claim2["id"], ADMIN))
    # budget 24000; first consumed 12000; remaining 12000; min(12000,12000)=12000
    assert approved2["final_cents"] == 12000


def test_claim_final_prorated_when_prior_consumed_budget(api):
    """PRD §3.8: "The remaining budget is the larger of zero and the contract's
    `annual_reimbursement_budget_cents` minus that spent total. The claim's
    `final_cents` is then the smaller of its `provisional_cents` and that
    remaining budget."

    Design: Difficulty/combinatorial_formula/claim_final_order_dependent_budget_consumption
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        contract_overrides={"sessions_per_issue": 2, "annual_session_cap": 10,
                            "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 20000},
        plan_overrides={"copay_cents": 0},
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    s2 = schedule_session(case["id"], provider["id"], "2026-03-03T10:00:00Z")
    complete_session(s1["id"], provider)
    complete_session(s2["id"], provider)
    claim1 = fx.submit_claim(contract["id"], s1["id"], 70000, provider)  # provisional 12000
    claim2 = fx.submit_claim(contract["id"], s2["id"], 70000, provider)  # provisional 12000
    validate_success(api.review_claim(claim1["id"], ADMIN))
    validate_success(api.approve_claim(claim1["id"], ADMIN))  # consumes 12000
    validate_success(api.review_claim(claim2["id"], ADMIN))
    approved2 = validate_success(api.approve_claim(claim2["id"], ADMIN))
    # remaining 20000-12000=8000; min(12000,8000)=8000
    assert approved2["final_cents"] == 8000


# ===========================================================================
# Cyclic state machine: reject -> resubmit -> review again  (Difficulty)
# ===========================================================================
def test_claim_cyclic_reject_resubmit_review_again(api):
    """PRD §3.8: "**Resubmission** is performed by the `Provider` on a `REJECTED`
    claim, supplying a corrected `billed_cents`; it moves the claim to
    `RESUBMITTED` and recomputes `provisional_cents` from the corrected amount,
    re-entering the adjudication cycle."
    PRD §3.8: "**Review** moves a claim from `SUBMITTED` (or from `RESUBMITTED`) to
    `UNDER_REVIEW`, and is permitted only when the session named by `session_id`
    is `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_reject_resubmit_review_again
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"sessions_per_issue": 1, "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 1_000_000},
        plan_overrides={"copay_cents": 2000})
    claim = fx.submit_claim(contract["id"], session["id"], 5000, provider)
    validate_success(api.review_claim(claim["id"], ADMIN))
    validate_success(api.reject_claim(claim["id"], ADMIN))
    resubmitted = validate_success(api.resubmit_claim(
        claim["id"], {"billed_cents": 20000}, make_provider_headers(provider["id"])))
    assert resubmitted["status"] == "RESUBMITTED"
    # billed 20000 capped to base 12000, minus copay 2000 -> provisional 10000
    assert resubmitted["provisional_cents"] == 10000
    reviewed = validate_success(api.review_claim(claim["id"], ADMIN))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["provisional_cents"] == 10000


def test_claim_resubmit_recomputes_provisional(api):
    """PRD §3.8: "**Resubmission** is performed by the `Provider` on a `REJECTED`
    claim, supplying a corrected `billed_cents`; it moves the claim to
    `RESUBMITTED` and recomputes `provisional_cents` from the corrected amount,
    re-entering the adjudication cycle."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_reject_resubmit_review_again
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"sessions_per_issue": 1, "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 1_000_000},
        plan_overrides={"copay_cents": 2000})
    claim = fx.submit_claim(contract["id"], session["id"], 5000, provider)
    # billed 5000 (< base 12000), minus copay 2000 -> 3000
    assert claim["provisional_cents"] == 3000
    validate_success(api.review_claim(claim["id"], ADMIN))
    validate_success(api.reject_claim(claim["id"], ADMIN))
    resubmitted = validate_success(api.resubmit_claim(
        claim["id"], {"billed_cents": 8000}, make_provider_headers(provider["id"])))
    # billed 8000 (< base 12000), minus copay 2000 -> 6000
    assert resubmitted["provisional_cents"] == 6000


# ===========================================================================
# Cross-entity: review requires session COMPLETED  (Difficulty)
# ===========================================================================
def test_claim_review_requires_session_completed(api):
    """PRD §3.8: "**Review** moves a claim from `SUBMITTED` (or from
    `RESUBMITTED`) to `UNDER_REVIEW`, and is permitted only when the session named
    by `session_id` is `COMPLETED`; otherwise it fails with
    `ERR_SESSION_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_session_completed
    """
    contract, plan, employee, provider, case = setup_authorized_case(
        clock="2026-03-02T09:00:00Z")
    s1 = schedule_session(case["id"], provider["id"], "2026-03-02T10:00:00Z")
    # session still SCHEDULED; submit a claim against it
    claim = fx.submit_claim(contract["id"], s1["id"], 12000, provider)
    validate_error(api.review_claim(claim["id"], ADMIN),
                   ApiErrorId.ERR_SESSION_NOT_COMPLETED.value)
    assert validate_success(api.get_claim(claim["id"], ADMIN))["status"] == "SUBMITTED"


def test_claim_review_succeeds_when_session_completed(api):
    """PRD §3.8: "**Review** moves a claim from `SUBMITTED` (or from
    `RESUBMITTED`) to `UNDER_REVIEW`, and is permitted only when the session named
    by `session_id` is `COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_session_completed
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session()
    claim = fx.submit_claim(contract["id"], session["id"], 12000, provider)
    reviewed = validate_success(api.review_claim(claim["id"], ADMIN))
    assert reviewed["status"] == "UNDER_REVIEW"


# ===========================================================================
# Corner: OON provisional, paid invalid state, duplicate claim
# ===========================================================================
def test_claim_out_of_network_provisional_uses_70pct_factor(api):
    """PRD §3.8: "If the payee provider's `network_status` is `OUT_OF_NETWORK`,
    that base is reduced to seventy percent by multiplying it by seven and then
    taking the floor of the result divided by ten — this floor is the only
    rounding step in the calculation. The reimbursable gross is then the smaller
    of the submitted `billed_cents` and that (possibly reduced) base."

    Design: Corner/calculations/claim_out_of_network_provisional_uses_70pct_factor
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"sessions_per_issue": 1, "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 100000},
        plan_overrides={"copay_cents": 2000},
        provider_overrides={"network_status": "OUT_OF_NETWORK", "specialties": ["STRESS"]})
    # base = floor(12000*7/10) = 8400; billed 15000 capped to 8400; -copay 2000 -> 6400
    claim = fx.submit_claim(contract["id"], session["id"], 15000, provider)
    assert claim["provisional_cents"] == 6400


def test_claim_review_from_paid_returns_invalid_state(api):
    """PRD §3.8: "an approved claim is paid as `PAID`, which is terminal."

    Design: Corner/state_machines/claim_review_from_paid_returns_invalid_state
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"sessions_per_issue": 1, "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 100000},
        plan_overrides={"copay_cents": 0})
    claim = fx.submit_claim(contract["id"], session["id"], 12000, provider)
    validate_success(api.review_claim(claim["id"], ADMIN))
    validate_success(api.approve_claim(claim["id"], ADMIN))
    validate_success(api.pay_claim(claim["id"], ADMIN))
    validate_error(api.review_claim(claim["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_claim(claim["id"], ADMIN))["status"] == "PAID"


def test_duplicate_claim_for_session_rejected(api):
    """PRD §3.8: "At most one live claim may exist per session: if a non-`REJECTED`
    claim already exists for the same `session_id`, the submission is rejected with
    `ERR_CLAIM_ALREADY_CLAIMED`."

    Design: Corner/validations/duplicate_claim_for_session_rejected
    """
    contract, plan, employee, provider, case, session = fx.setup_completed_session(
        contract_overrides={"sessions_per_issue": 1, "session_rate_cents": 12000,
                            "annual_reimbursement_budget_cents": 100000})
    fx.submit_claim(contract["id"], session["id"], 12000, provider)
    validate_error(api.create_claim(
        create_claim_payload(contract["id"], session["id"], 12000),
        make_provider_headers(provider["id"])),
        ApiErrorId.ERR_CLAIM_ALREADY_CLAIMED.value)
