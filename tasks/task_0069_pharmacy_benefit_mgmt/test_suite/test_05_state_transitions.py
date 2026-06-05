"""Invalid / terminal state transitions and finalize no-op (PRD §2.7, §3.3, §3.7).
Corner queue: state_machines section.
"""
from test_helpers import fixtures as fx, validate_error, validate_success, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers import make_director_headers, make_reviewer_headers


# ─── Corner / state_machines.pa_decide_on_already_approved ──────────────────
def test_decide_already_approved_pa_returns_invalid_state(api):
    """PRD §3.3: "A decision is only legal while the authorization is in `PENDING_REVIEW` or `APPEALED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pa_decide_on_already_approved_returns_invalid_state
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=1)
    resp = api_client.decide_prior_authorization(
        pa["id"],
        {"decision": "DENY", "expected_prior_authorization_version": pa["version"]},
        make_director_headers("U_DIR"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_pa(pa["id"])["status"] == "APPROVED"


# ─── Corner / state_machines.appeal_on_pending_pa ───────────────────────────
def test_appeal_pending_pa_returns_invalid_state(api):
    """PRD §3.3: "A denied authorization is not the end of the road: a
    `PharmacistReviewer` may appeal it, moving it from `DENIED` to `APPEALED`"
    PRD §2.7: "an operation that drives a state transition requires its target to be in
    a state that permits the transition (a prior authorization must be in
    `PENDING_REVIEW` or `APPEALED` to be decided, a claim must be `PAID` to be reversed,
    a rebate accrual must be `PROVISIONAL` to be finalized), and a violation yields
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/appeal_on_pending_pa_returns_invalid_state
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    resp = api_client.appeal_prior_authorization(pa["id"], make_reviewer_headers("U_REV"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner / state_machines.reverse_already_reversed_claim ─────────────────
def test_reverse_already_reversed_claim_returns_invalid_state(api):
    """PRD §3.7: "Reversing a claim is a `PharmacyProvider` action permitted only while
    the claim is `PAID`"
    PRD §2.7: "a claim must be `PAID` to be reversed"

    Design: Corner/state_machines/reverse_already_reversed_claim_returns_invalid_state
    """
    fx.set_clock("2026-06-10T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Z", drug_name="Z", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    fx.reverse_claim(claim["id"])
    resp = api_client.reverse_claim(claim["id"], fx.PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner / state_machines.terminal_expired_pa_rejects_decide ─────────────
def test_expired_pa_rejects_decide(api):
    """PRD §3.3: "an `APPROVED` authorization moves automatically to `EXPIRED` — a terminal state — at the moment a paid claim consumes its last authorized fill"
    PRD §3.3: "A decision is only legal while the authorization is in `PENDING_REVIEW` or `APPEALED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_expired_pa_rejects_decide
    """
    fx.set_clock("2026-06-20T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PA", drug_name="PA", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=1)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID"
    pa_expired = fx.get_pa(pa["id"])
    assert pa_expired["status"] == "EXPIRED"
    resp = api_client.decide_prior_authorization(
        pa["id"],
        {"decision": "DENY", "expected_prior_authorization_version": pa_expired["version"]},
        make_director_headers("U_DIR"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner / state_machines.finalize_rebates_on_already_finalized_is_noop ──
def test_second_finalize_sweep_is_noop(api):
    """PRD §3.7: "A `PlanAdmin` periodically runs the rebate-finalization sweep for a
    plan, which moves every `PROVISIONAL` accrual whose underlying claim is still `PAID`
    to `FINALIZED`"
    PRD §3.7: "and it reports back a `finalized_count` and the list of
    `finalized_accrual_ids`."

    Design: Corner/state_machines/finalize_rebates_on_already_finalized_is_noop
    """
    plan, drug, member, claim, accrual = fx.setup_finalized_rebate_claim(
        clock="2026-06-25T00:00:00.000Z", clawback_pct=1.0, rebate_per_fill_cents=4000,
        tier="TIER_1", ingredient_cost_cents=10000,
    )
    assert accrual["status"] == "FINALIZED"
    # Re-read the plan's current version (the first finalize bumped it).
    plan_now = validate_success(api_client.get_plan(plan["id"], fx.ADMIN), 200)
    resp = api_client.finalize_rebates(
        plan["id"], {"expected_benefit_plan_version": plan_now["version"]}, fx.ADMIN)
    data = validate_success(resp, 200)
    assert data["finalized_count"] == 0, data["finalized_count"]
