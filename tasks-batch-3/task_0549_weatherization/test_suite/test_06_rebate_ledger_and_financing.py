"""Rebate budget ledger (approve/void, budget cap, state-vs-fiscal precedence,
immediate consistency), WAP-track gating, and financing (amortization,
supersede, respond, and the OCC stale-version guard)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_job_payload,
    create_financing_plan_payload,
    new_dwelling,
    new_job,
    setup_rebate_submitted,
    setup_rebate_approved,
    setup_rebate_denied,
    setup_financing_offered,
)


# ── rebate_money_conserved_on_void ────────────────────────────────────────
def test_void_moves_rebate_to_voided(api, program_admin_headers):
    """PRD 3.7: "Voiding moves the claim to `VOIDED` (terminal), subtracts its
    `finalized_amount_cents` back out of the job's `approved_rebate_total_cents`
    so the total returns to its pre-approval value, and recomputes
    `estimated_out_of_pocket_cents`."

    Design: Difficulty/compensating_invariant/rebate_money_conserved_on_void
    """
    ctx = setup_rebate_approved(cap=300_000, target_r=38, achieved_r=25, estimated_cost=100_000, actual_cost=100_000)
    rebate = validate_success(api.void_rebate_claim(ctx["rebate"]["id"], program_admin_headers), 200)
    assert rebate["status"] == "VOIDED"


def test_void_returns_approved_total_to_pre_approval(api, program_admin_headers):
    """PRD 3.7: "Voiding moves the claim to `VOIDED` (terminal), subtracts its
    `finalized_amount_cents` back out of the job's `approved_rebate_total_cents`
    so the total returns to its pre-approval value, and recomputes
    `estimated_out_of_pocket_cents`."

    Design: Difficulty/compensating_invariant/rebate_money_conserved_on_void
    """
    ctx = setup_rebate_approved(cap=300_000, target_r=38, achieved_r=25, estimated_cost=100_000, actual_cost=100_000)
    api.void_rebate_claim(ctx["rebate"]["id"], program_admin_headers)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 0


# ── state_beats_fiscal_on_rebate_approve (priority 7 over 11) ─────────────
def test_denied_claim_approve_returns_invalid_state(api, program_admin_headers):
    """PRD 2.5: "Lower-numbered checks take priority over higher-numbered ones".
    PRD 2.5: "7. **State precondition** — the target resource must be in the
    state its transition requires, or `ERR_INVALID_STATE` (409)."
    PRD 2.5: "11. **Rebate budget** — approving a rebate must not push the job's
    approved rebate total above its cap, or `ERR_REBATE_BUDGET_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_rebate_approve
    """
    ctx = setup_rebate_denied(cap=40_000, target_r=30, achieved_r=30, estimated_cost=100_000, actual_cost=100_000)
    res = api.decide_rebate_claim(ctx["rebate"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_denied_claim_stays_denied_with_no_budget_change(api, program_admin_headers):
    """PRD 3.7: "A `decision` of `DENY` moves a `SUBMITTED` claim to `DENIED`,
    which is terminal. Deciding a claim that is not `SUBMITTED` fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_rebate_approve
    """
    ctx = setup_rebate_denied(cap=40_000, target_r=30, achieved_r=30, estimated_cost=100_000, actual_cost=100_000)
    api.decide_rebate_claim(ctx["rebate"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["status"] == "DENIED"
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 0


# ── rebate_approve_over_budget_returns_budget_exceeded (corner) ───────────
def test_rebate_approve_over_budget_rejected(api, program_admin_headers):
    """PRD 3.7: "A `decision` of `APPROVE` moves a `SUBMITTED` claim to
    `APPROVED`, but only if doing so keeps the budget in bounds: the job's
    current `approved_rebate_total_cents` plus this claim's
    `finalized_amount_cents` must not exceed the job's `rebate_budget_cap_cents`,
    or the approval is rejected with `ERR_REBATE_BUDGET_EXCEEDED`."

    Design: Corner/validations/rebate_approve_over_budget_returns_budget_exceeded
    """
    ctx = setup_rebate_submitted(cap=40_000, target_r=30, achieved_r=30, estimated_cost=100_000, actual_cost=100_000)
    res = api.decide_rebate_claim(ctx["rebate"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_REBATE_BUDGET_EXCEEDED)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["status"] == "SUBMITTED"
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 0


# ── approved_rebate_visible_immediately_on_job_read (corner) ─────────────
def test_approved_rebate_visible_immediately_on_job_read(api, program_admin_headers):
    """PRD 3.7: "On approval the claim's `finalized_amount_cents` is added to the
    job's `approved_rebate_total_cents` and the job's
    `estimated_out_of_pocket_cents` is recomputed."

    Design: Corner/consistency_model/approved_rebate_visible_immediately_on_job_read
    """
    ctx = setup_rebate_submitted(cap=300_000, target_r=38, achieved_r=25, estimated_cost=100_000, actual_cost=100_000)
    api.decide_rebate_claim(ctx["rebate"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["approved_rebate_total_cents"] == 50_000
    assert job["estimated_out_of_pocket_cents"] == 20_000


# ── wap_track_job_without_eligible_app_returns_not_wap_eligible (corner) ──
def test_wap_track_job_without_eligible_app_rejected(api, program_admin_headers):
    """PRD 3.2: "When the track is `WAP`, the job may be created only if the
    referenced dwelling already has a WAP application whose `status` is
    `ELIGIBLE`; if no eligible application exists for that dwelling, creation is
    rejected with `ERR_NOT_WAP_ELIGIBLE`."

    Design: Corner/validations/wap_track_job_without_eligible_app_returns_not_wap_eligible
    """
    dwelling = new_dwelling()
    res = api.create_job(
        create_job_payload(dwelling["id"], program_track="WAP", rebate_budget_cap_cents=100_000),
        program_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOT_WAP_ELIGIBLE)


# ── financing_amortization_monthly_payment (corner) ──────────────────────
def test_financing_amortization_monthly_payment(api, program_admin_headers):
    """PRD 3.9: "Otherwise `monthly_payment_cents` is `principal_cents`
    multiplied by the monthly rate, divided by the quantity one minus (one plus
    the monthly rate) raised to the power of the negative `term_months`, with the
    final result rounded half up to whole cents."

    Design: Corner/calculations/financing_amortization_monthly_payment
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    payload = create_financing_plan_payload(job["id"], job["version"], principal_cents=500_000, term_months=60, apr_bps=600)
    plan = validate_success(api.create_financing_plan(payload, program_admin_headers), 201)
    assert plan["monthly_payment_cents"] == 9666
    assert plan["status"] == "OFFERED"


# ── financing_second_offer_supersedes_first (corner) ─────────────────────
def test_financing_second_offer_supersedes_first(api, program_admin_headers):
    """PRD 3.9: "Offering a new plan for a job automatically supersedes any
    existing plan for that job that is still in `OFFERED` status, moving the
    prior plan from `OFFERED` to `SUPERSEDED`, and advances the job's
    `version`".

    Design: Corner/state_machines/financing_second_offer_supersedes_first
    """
    ctx = setup_financing_offered(principal=500_000, term=60, apr=600)
    payload = create_financing_plan_payload(ctx["job"]["id"], ctx["job_after"]["version"], principal_cents=400_000, term_months=48, apr_bps=500)
    fp_b = validate_success(api.create_financing_plan(payload, program_admin_headers), 201)
    assert fp_b["status"] == "OFFERED"
    fp_a = validate_success(api.get_financing_plan(ctx["financing"]["id"], program_admin_headers))
    assert fp_a["status"] == "SUPERSEDED"


# ── financing_respond_accept_from_offered (corner) ───────────────────────
def test_financing_respond_accept_from_offered(api, homeowner_headers):
    """PRD 3.9: "A `Homeowner` responds to an offered plan by supplying a
    `decision`: a `decision` of `ACCEPT` moves an `OFFERED` plan to `ACCEPTED`".

    Design: Corner/state_machines/financing_respond_accept_from_offered
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    payload = create_financing_plan_payload(job["id"], job["version"], principal_cents=300_000, term_months=36, apr_bps=700)
    plan = validate_success(api.create_financing_plan(payload, homeowner_headers), 201)
    res = api.respond_financing_plan(plan["id"], {"decision": "ACCEPT"}, homeowner_headers)
    updated = validate_success(res, 200)
    assert updated["status"] == "ACCEPTED"


# ── financing_create_stale_job_version_returns_412 (corner) ──────────────
def test_financing_create_stale_job_version_rejected(api, program_admin_headers):
    """PRD 2.9: "Before the offer is created, the server compares
    `expected_job_version` against the job's current `version`; if they differ,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan is
    created."

    Design: Corner/cross_cutting_complexity_layers/financing_create_stale_job_version_returns_412
    """
    ctx = setup_financing_offered(principal=500_000, term=60, apr=600)
    # ctx["job"] carries the pre-supersede (now stale) version.
    payload = create_financing_plan_payload(ctx["job"]["id"], ctx["job"]["version"], principal_cents=450_000, term_months=60, apr_bps=600)
    res = api.create_financing_plan(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    fp_a = validate_success(api.get_financing_plan(ctx["financing"]["id"], program_admin_headers))
    assert fp_a["status"] == "OFFERED"


# ── financing_create_increments_job_version (corner) ─────────────────────
def test_financing_create_increments_job_version(api, program_admin_headers):
    """PRD 2.4: "The operations that advance a job's `version` are: completing
    its install dimension, running verification, cancelling it, offering a
    financing plan against it, and the crew assignment that first moves its
    install dimension from `PLANNED` to `SCHEDULED`."

    Design: Corner/cross_cutting_complexity_layers/financing_create_increments_job_version
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    payload = create_financing_plan_payload(job["id"], job["version"], principal_cents=500_000, term_months=60, apr_bps=600)
    validate_success(api.create_financing_plan(payload, program_admin_headers), 201)
    job_after = validate_success(api.get_job(job["id"], program_admin_headers))
    assert job_after["version"] == 2
