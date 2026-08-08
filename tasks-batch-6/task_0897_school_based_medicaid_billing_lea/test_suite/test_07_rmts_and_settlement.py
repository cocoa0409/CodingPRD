"""RMTS study and cost settlement: the interim-FFS vs cost-settled dual variant,
the nested rounding chain, the responded-moments close boundary, and the
quarter/version settlement corners (OCC).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    setup_claim_with_verified_log, setup_closed_quarter_half_ratio,
    create_settlement, create_quarter, create_quarter_with_coded_moments, close_quarter,
    create_settlement_payload,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]


# --- dual_variant_calc / interim_ffs_vs_cost_settled_reimbursement -----------
def _interim_vs_cost_scenario():
    claim_ctx = setup_claim_with_verified_log()   # 40 min -> 3 units -> 9000c attached
    q = setup_closed_quarter_half_ratio(fiscal_quarter="2026-Q1")
    settlement = create_settlement(
        q["quarter_id"], q["quarter_version"],
        certified_cost_cents=1000000, iep_ratio_bps=4000, fmap_bps=5000, interim_paid_cents=9000)
    return claim_ctx, q, settlement


def test_interim_ffs_charge_and_quarter_ratio(api):
    """PRD §3.5: "On APPROVE, the claim moves to PAID; its interim_payment_cents is
    fixed to equal its total_charge_cents at that moment (the full fee-schedule
    allowed amount ...)".
    PRD §3.7: "The ratio is medicaid_eligible_moments divided by responded_moments,
    rounded half-up to four decimal places, and while the quarter is open it
    remains 0."

    Design: Difficulty/dual_variant_calc/interim_ffs_vs_cost_settled_reimbursement
    """
    claim_ctx, q, _settlement = _interim_vs_cost_scenario()
    claim = get_success_data(api.get_claim(claim_ctx["claim"]["id"], MC))
    assert claim["total_charge_cents"] == 9000
    assert q["quarter"]["medicaid_eligibility_ratio"] == pytest.approx(0.5)


def test_cost_settled_federal_share_differs_from_ffs_charge(api):
    """PRD §3.8: "The federal_share_cents is gross_medicaid_cost_cents multiplied by
    fmap_bps and divided by 10000, rounded half-up to whole cents; this is the
    cost-settled reimbursement. Finally, net_settlement_cents is
    federal_share_cents minus the supplied interim_paid_cents".
    PRD §3.8: "This cost-settled federal share is the dual-variant counterpart to
    the interim FFS payments: computed on a cost basis, it generally differs in
    amount from the fee-schedule interim reimbursement for the same services."

    Design: Difficulty/dual_variant_calc/interim_ffs_vs_cost_settled_reimbursement
    """
    claim_ctx, _q, settlement = _interim_vs_cost_scenario()
    claim = get_success_data(api.get_claim(claim_ctx["claim"]["id"], MC))
    assert settlement["federal_share_cents"] == 100000
    assert settlement["net_settlement_cents"] == 91000
    assert claim["total_charge_cents"] != settlement["federal_share_cents"]


# --- combinatorial_formula / cost_settlement_nested_ratio_chain --------------
def _negative_net_settlement():
    q = setup_closed_quarter_half_ratio(fiscal_quarter="2026-Q2")
    settlement = create_settlement(
        q["quarter_id"], q["quarter_version"],
        certified_cost_cents=1000000, iep_ratio_bps=4000, fmap_bps=5000, interim_paid_cents=150000)
    return q, settlement


def test_settlement_nested_rounding_chain_gross_and_federal(api):
    """PRD §3.8: "Starting from the quarter's fixed medicaid_eligibility_ratio, the
    Medicaid-allocated cost is certified_cost_cents multiplied by that ratio,
    rounded half-up to whole cents. The gross_medicaid_cost_cents is that
    Medicaid-allocated cost multiplied by iep_ratio_bps and divided by 10000,
    rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/cost_settlement_nested_ratio_chain
    """
    _q, settlement = _negative_net_settlement()
    assert settlement["gross_medicaid_cost_cents"] == 200000
    assert settlement["federal_share_cents"] == 100000


def test_settlement_negative_net_is_recoupment(api):
    """PRD §3.8: "net_settlement_cents is federal_share_cents minus the supplied
    interim_paid_cents, and may be negative — a negative net settlement represents
    a recoupment the LEA owes back to the state."

    Design: Difficulty/combinatorial_formula/cost_settlement_nested_ratio_chain
    """
    q, settlement = _negative_net_settlement()
    assert q["quarter"]["medicaid_eligibility_ratio"] == pytest.approx(0.5)
    assert settlement["net_settlement_cents"] == -50000


# --- boundary_precision_check / rmts_min_responded_moments_boundary ----------
def test_quarter_close_with_three_moments_rejected(api):
    """PRD §3.7: "A close is permitted only when responded_moments is at least 4; a
    close attempted with fewer than 4 responded moments is rejected with
    ERR_INSUFFICIENT_SAMPLE (HTTP 422), where exactly 4 passes and 3 fails."

    Design: Difficulty/boundary_precision_check/rmts_min_responded_moments_boundary
    """
    info = create_quarter_with_coded_moments(
        ["DIRECT_MEDICAL", "NON_MEDICAL", "MEDICAL_ADMIN"], fiscal_quarter="2026-Q3")
    resp = api.close_quarter(info["quarter_id"], MC)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SAMPLE)
    assert get_success_data(api.get_quarter(info["quarter_id"], MC))["responded_moments"] == 3


def test_quarter_close_with_four_moments_accepted(api):
    """PRD §3.7: "A close is permitted only when responded_moments is at least 4 ...
    where exactly 4 passes and 3 fails."

    Design: Difficulty/boundary_precision_check/rmts_min_responded_moments_boundary
    """
    info = create_quarter_with_coded_moments(
        ["DIRECT_MEDICAL", "MEDICAL_ADMIN", "NON_MEDICAL", "GENERAL_ADMIN"], fiscal_quarter="2026-Q3")
    closed = validate_success(api.close_quarter(info["quarter_id"], MC))
    assert closed["status"] == "CLOSED"


# --- validations / cost_settlement_quarter_not_closed ------------------------
def test_cost_settlement_against_open_quarter_returns_error(api):
    """PRD §3.8: "The linked quarter must be in status CLOSED, else the create is
    rejected with ERR_QUARTER_NOT_CLOSED (HTTP 422)."

    Design: Corner/validations/cost_settlement_quarter_not_closed_returns_error
    """
    quarter = create_quarter(fiscal_quarter="2027-Q2")
    resp = api.create_settlement(create_settlement_payload(
        rmts_quarter_id=quarter["id"], expected_rmts_quarter_version=quarter["version"],
        interim_paid_cents=0), MC)
    validate_error(resp, ApiErrorId.ERR_QUARTER_NOT_CLOSED)


# --- cross_cutting_complexity_layers / settlement OCC ------------------------
def test_settlement_create_stale_quarter_version_conflict(api):
    """PRD §2.7: "A settlement-create request must carry expected_rmts_quarter_version,
    a required input field holding the version of the target RMTSQuarter that the
    client last observed. If that value does not equal the quarter's current
    version, the create is rejected with ERR_STALE_QUARTER_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/settlement_create_stale_quarter_version_conflict
    """
    q = setup_closed_quarter_half_ratio(fiscal_quarter="2027-Q3")
    # First create succeeds and bumps the quarter version past the captured value.
    create_settlement(q["quarter_id"], q["quarter_version"], interim_paid_cents=0)
    resp = api.create_settlement(create_settlement_payload(
        rmts_quarter_id=q["quarter_id"], certified_cost_cents=900000,
        expected_rmts_quarter_version=q["quarter_version"], interim_paid_cents=0), MC)
    validate_error(resp, ApiErrorId.ERR_STALE_QUARTER_VERSION)


def test_settlement_create_success_bumps_quarter_version(api):
    """PRD §2.7: "a new settlement legitimately supersedes a prior one for the same
    closed quarter — corrections re-run the reconciliation — and each successful
    settlement create increments the quarter's version by one."

    Design: Corner/cross_cutting_complexity_layers/settlement_create_success_bumps_quarter_version
    """
    q = setup_closed_quarter_half_ratio(fiscal_quarter="2027-Q4")
    settlement = create_settlement(q["quarter_id"], q["quarter_version"], interim_paid_cents=0)
    assert settlement["status"] == "CALCULATED"
    bumped = get_success_data(api.get_quarter(q["quarter_id"], MC))
    assert bumped["version"] == q["quarter_version"] + 1
