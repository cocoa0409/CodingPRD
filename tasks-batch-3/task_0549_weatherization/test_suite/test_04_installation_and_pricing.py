"""Install completion, the 25C tax credit's pinned per-line rounding, and the
provisional/finalized/tiered/capped rebate pricing."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rebate_claim_payload,
    new_dwelling,
    new_job,
    new_audit,
    new_scope,
    new_rebate,
    setup_installed_scope,
    setup_two_attic_scopes_first_installed,
    setup_rebate_draft,
    setup_rebate_submitted,
    setup_draft_rebate_on_approved_scope,
)


# ── job_parallel_install_and_verification_dimensions ──────────────────────
def test_complete_install_sets_install_status_installed(api, program_admin_headers):
    """PRD 3.6: "Completing the install dimension is a separate `ProgramAdmin`
    action that moves the job's `install_status` from `SCHEDULED` to
    `INSTALLED`."

    Design: Difficulty/non_linear_state_machine/job_parallel_install_and_verification_dimensions
    """
    ctx = setup_installed_scope(cap=100_000, achieved_r=30, actual_cost=100_000, estimated_cost=100_000, estimated_savings=500)
    job = validate_success(api.complete_install(ctx["job"]["id"], program_admin_headers), 200)
    assert job["install_status"] == "INSTALLED"


def test_verification_stays_pending_after_install(api, program_admin_headers):
    """PRD 2.8: "`install_status` and `verification_status` are **parallel,
    independent dimensions**: one advances through crew scheduling and install
    completion, the other through post-test verification, and neither gates the
    other's transitions except where a workflow explicitly says so."

    Design: Difficulty/non_linear_state_machine/job_parallel_install_and_verification_dimensions
    """
    ctx = setup_installed_scope(cap=100_000, achieved_r=30, actual_cost=100_000, estimated_cost=100_000, estimated_savings=500)
    job = validate_success(api.complete_install(ctx["job"]["id"], program_admin_headers), 200)
    assert job["verification_status"] == "PENDING"
    assert job["job_status"] == "ACTIVE"


# ── tax_credit_25c_per_line_rounding_mode_b ───────────────────────────────
def test_tax_credit_per_line_rounding(api, installer_headers, program_admin_headers):
    """PRD 3.6: "The evaluation order is pinned and must not be reordered:
    **round each measure's credit to whole dollars first, then sum the rounded
    per-measure credits, then apply the annual cap.**"

    Design: Difficulty/combinatorial_formula/tax_credit_25c_per_line_rounding_mode_b
    """
    ctx = setup_two_attic_scopes_first_installed(actual_cost=33_500)
    api.mark_installed(ctx["scope2"]["id"], {"achieved_r_value": 30, "actual_cost_cents": 33_500}, installer_headers)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["tax_credit_cents"] == 20_200


def test_tax_credit_not_sum_then_round(api, installer_headers, program_admin_headers):
    """PRD 3.6: "the per-measure credit is 30% of that measure's
    `actual_cost_cents`, rounded to the nearest whole dollar — that is, take
    0.30 times `actual_cost_cents`, round that amount half up to a whole number
    of dollars, and express it back in cents as a multiple of 100."

    Design: Difficulty/combinatorial_formula/tax_credit_25c_per_line_rounding_mode_b
    """
    ctx = setup_two_attic_scopes_first_installed(actual_cost=33_500)
    api.mark_installed(ctx["scope2"]["id"], {"achieved_r_value": 30, "actual_cost_cents": 33_500}, installer_headers)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    # Per-line rounding: round(100.50)->101 each -> 20200, not sum-then-round 20100.
    assert job["tax_credit_cents"] == 20_200
    assert job["tax_credit_cents"] != 20_100


# ── rebate_provisional_vs_finalized ───────────────────────────────────────
def test_rebate_provisional_from_target_r_value(api, program_admin_headers):
    """PRD 3.7: "its `provisional_amount_cents` is computed immediately from the
    tiered rebate schedule using the scope item's `target_r_value`."

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_finalized
    """
    ctx = setup_rebate_draft(target_r=38, achieved_r=25, actual_cost=320_000)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["provisional_amount_cents"] == 90_000


def test_rebate_finalized_from_achieved_r_value(api, program_admin_headers):
    """PRD 3.7: "Submitting a rebate claim moves it from `DRAFT` to `SUBMITTED`
    and recomputes the rebate as `finalized_amount_cents` using the same
    schedule and cap but keyed on the measure's `achieved_r_value` rather than
    its `target_r_value`".

    Design: Difficulty/dual_variant_calc/rebate_provisional_vs_finalized
    """
    ctx = setup_rebate_draft(target_r=38, achieved_r=25, actual_cost=320_000)
    rebate = validate_success(api.submit_rebate_claim(ctx["rebate"]["id"], program_admin_headers), 200)
    assert rebate["finalized_amount_cents"] == 50_000
    assert rebate["provisional_amount_cents"] != rebate["finalized_amount_cents"]


# ── rebate_tiered_nested_min_mode_a ───────────────────────────────────────
def _wall_r50_scope():
    dwelling = new_dwelling(address="3 Pine St")
    job = new_job(dwelling["id"], rebate_budget_cap_cents=500_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="WALL_INSULATION", area_sqft=3000, target_r_value=50,
        estimated_cost_cents=500_000, estimated_savings_kwh=900,
    )
    return job, scope


def test_wall_insulation_tier3_capped_provisional(api, program_admin_headers):
    """PRD 3.7: "wall insulation pays 40, 70, or 100" [cents per square foot for
    tiers 1, 2, and 3]. PRD 3.7: "The raw rebate is the applicable rate
    multiplied by the measure's `area_sqft`, rounded half up to whole cents, and
    the stored amount is capped at the per-measure ceiling of 200,000 cents
    ($2,000)."

    Design: Difficulty/combinatorial_formula/rebate_tiered_nested_min_mode_a
    """
    job, scope = _wall_r50_scope()
    res = api.create_rebate_claim(create_rebate_claim_payload(job["id"], scope["id"]), program_admin_headers)
    rebate = validate_success(res, 201)
    assert rebate["provisional_amount_cents"] == 200_000


def test_rebate_capped_at_measure_ceiling(api, program_admin_headers):
    """PRD 3.7: "The raw rebate is the applicable rate multiplied by the
    measure's `area_sqft`, rounded half up to whole cents, and the stored amount
    is capped at the per-measure ceiling of 200,000 cents ($2,000)."

    Design: Difficulty/combinatorial_formula/rebate_tiered_nested_min_mode_a
    """
    job, scope = _wall_r50_scope()
    res = api.create_rebate_claim(create_rebate_claim_payload(job["id"], scope["id"]), program_admin_headers)
    rebate = validate_success(res, 201)
    # 100 cents/sqft * 3000 sqft = 300000 raw, capped to the 200000 ceiling.
    assert rebate["provisional_amount_cents"] == 200_000
    assert rebate["provisional_amount_cents"] < 300_000


# ── rebate_submit_requires_scope_installed ────────────────────────────────
def test_submit_rebate_with_approved_scope_rejected(api, program_admin_headers):
    """PRD 3.7: "Submission is permitted only when the claim is in `DRAFT`
    (otherwise `ERR_INVALID_STATE`) and only when the referenced scope item is
    in `INSTALLED` or `VERIFIED` status; a claim whose measure is not yet
    installed is rejected with `ERR_SCOPE_NOT_INSTALLED`."

    Design: Difficulty/cross_entity_state_dependency/rebate_submit_requires_scope_installed
    """
    ctx = setup_draft_rebate_on_approved_scope()
    res = api.submit_rebate_claim(ctx["rebate"]["id"], program_admin_headers)
    validate_error(res, ApiErrorId.ERR_SCOPE_NOT_INSTALLED)


def test_rebate_stays_draft_when_scope_not_installed(api, program_admin_headers):
    """PRD 3.7: "Submission is permitted only when the claim is in `DRAFT`
    (otherwise `ERR_INVALID_STATE`) and only when the referenced scope item is
    in `INSTALLED` or `VERIFIED` status; a claim whose measure is not yet
    installed is rejected with `ERR_SCOPE_NOT_INSTALLED`."

    Design: Difficulty/cross_entity_state_dependency/rebate_submit_requires_scope_installed
    """
    ctx = setup_draft_rebate_on_approved_scope()
    api.submit_rebate_claim(ctx["rebate"]["id"], program_admin_headers)
    rebate = validate_success(api.get_rebate_claim(ctx["rebate"]["id"], program_admin_headers))
    assert rebate["status"] == "DRAFT"


# ── Corner: job_financial_rollup_out_of_pocket ────────────────────────────
def test_job_financial_rollup_out_of_pocket(api, program_admin_headers):
    """PRD 3.6: "it sets `estimated_out_of_pocket_cents` to the greater of 0 and
    (`total_estimated_cost_cents` − `approved_rebate_total_cents` −
    `tax_credit_cents`), so the out-of-pocket balance is floored at zero."

    Design: Corner/calculations/job_financial_rollup_out_of_pocket
    """
    ctx = setup_rebate_submitted(cap=300_000, target_r=38, achieved_r=38, estimated_cost=300_000, actual_cost=200_000, area=1000)
    api.decide_rebate_claim(ctx["rebate"]["id"], {"decision": "APPROVE"}, program_admin_headers)
    job = validate_success(api.get_job(ctx["job"]["id"], program_admin_headers))
    assert job["total_estimated_cost_cents"] == 300_000
    assert job["tax_credit_cents"] == 60_000
    assert job["approved_rebate_total_cents"] == 90_000
    assert job["estimated_out_of_pocket_cents"] == 150_000


# ── Corner: rebate_air_sealing_flat_rate_no_tier ──────────────────────────
def test_air_sealing_flat_rate_provisional(api, program_admin_headers):
    """PRD 3.7: "The two sealing categories carry no tier and use a flat rate:
    air sealing pays 25 cents per square foot and duct sealing pays 20 cents per
    square foot regardless of R-value."

    Design: Corner/calculations/rebate_air_sealing_flat_rate_no_tier
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="AIR_SEALING", area_sqft=800, target_r_value=0,
        estimated_cost_cents=60_000, estimated_savings_kwh=300,
    )
    res = api.create_rebate_claim(create_rebate_claim_payload(job["id"], scope["id"]), program_admin_headers)
    rebate = validate_success(res, 201)
    assert rebate["provisional_amount_cents"] == 20_000
