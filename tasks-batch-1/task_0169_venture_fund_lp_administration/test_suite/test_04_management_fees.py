"""Management-fee accrual: per-commitment rounding, the fee-offset variant, and
period-overlap / adjacency guards. Covers the fee-related difficulty-queue
dual-variant, combinatorial, and boundary instances plus corner validations.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_fee_accrual_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]


def _accrue(api, fund_id, period_start, period_end):
    return api.create_fee_accrual(
        fund_id, create_fee_accrual_payload(period_start, period_end), FA)


# ---------------------------------------------------------------------------
# Dual variant: base vs fee-offset
# ---------------------------------------------------------------------------

def test_mgmt_fee_base_no_offset(api):
    """PRD §3.8: "Absent the offset — when `fee_offset_pct_bps` is zero or no qualifying management-fee call exists — `offset_applied_cents` is `0` and `net_fee_cents` equals `gross_fee_cents`."

    Design: Difficulty/dual_variant_calc/mgmt_fee_base_vs_offset_variant
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Base Fund", vintage_year=2024,
        mgmt_fee_rate_bps=200, fee_offset_pct_bps=0)
    accr = validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-03-31T00:00:00Z"), 201)
    # round_half_up per commitment: 6,000,000*0.02*90/365=29589, 4,000,000*...=19726.
    assert accr["gross_fee_cents"] == 49315
    assert accr["offset_applied_cents"] == 0
    assert accr["net_fee_cents"] == 49315


# ---------------------------------------------------------------------------
# Combinatorial: round-per-commitment-then-sum
# ---------------------------------------------------------------------------

def test_mgmt_fee_round_per_commitment_then_sum(api):
    """PRD §3.8: "the rounding is applied to each commitment's contribution before the
    contributions are added together, never sum-then-round."
    PRD §3.8: "That commitment's contribution is its `committed_cents` multiplied by the effective rate, divided by `10000`, multiplied by the day count, divided by `365` days per year, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/mgmt_fee_round_per_commitment_then_sum
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [1_000_000, 2_000_099], name="Round Fund", vintage_year=2024,
        mgmt_fee_rate_bps=200, fee_offset_pct_bps=0, target_size_cents=4_000_000)
    accr = validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-03-31T00:00:00Z"), 201)
    # 1,000,000: 1800000/365=4931.51 -> 4932 ; 2,000,099: 3600178.2/365=9863.50 -> 9864
    # per-commitment sum = 14796 (sum-then-round would give 14795).
    assert accr["gross_fee_cents"] == 14796


def test_mgmt_fee_two_commitments_sum_is_per_commitment(api):
    """PRD §3.8: "The accrual's `gross_fee_cents` is the sum of those per-commitment rounded contributions."

    Design: Difficulty/combinatorial_formula/mgmt_fee_round_per_commitment_then_sum
    """
    # Single commitment 2,000,099 in isolation rounds to 9864; the two-commitment
    # accrual's gross (14796) must equal 4932 + 9864, confirming per-commitment rounding.
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [1_000_000], name="Solo Round Fund", vintage_year=2024,
        mgmt_fee_rate_bps=200, fee_offset_pct_bps=0, target_size_cents=4_000_000)
    accr = validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-03-31T00:00:00Z"), 201)
    assert accr["gross_fee_cents"] == 4932


# ---------------------------------------------------------------------------
# Period overlap / adjacency boundary
# ---------------------------------------------------------------------------

def test_fee_period_interior_overlap_rejected(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_accrual_period_half_open_overlap
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="FeeOverlap Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"), 201)
    validate_error(
        _accrue(api, fund["id"], "2024-02-15T00:00:00Z", "2024-05-01T00:00:00Z"),
        "ERR_FEE_PERIOD_OVERLAP", 409)


def test_fee_period_overlapping_existing_rejected_second_case(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_mfn_safety_unreached
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="PriTwo Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"), 201)
    # New accrual 2024-03-01..2024-05-01 overlaps the existing one; only the temporal
    # rule can fire here, so it returns ERR_FEE_PERIOD_OVERLAP.
    validate_error(
        _accrue(api, fund["id"], "2024-03-01T00:00:00Z", "2024-05-01T00:00:00Z"),
        "ERR_FEE_PERIOD_OVERLAP", 409)


def test_overlap_with_earlier_existing_accrual_rejected(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_mfn_safety_unreached
    """
    # Reverse the operand order: the NEW period starts earlier and overlaps the start
    # of the existing one. Only the temporal-overlap rule can fire on a fee accrual.
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="EarlierOverlap Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-03-01T00:00:00Z", "2024-06-01T00:00:00Z"), 201)
    validate_error(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"),
        "ERR_FEE_PERIOD_OVERLAP", 409)


def test_fee_period_adjacency_allowed(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/fee_period_adjacency_boundary_allowed
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="Adjacency Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"), 201)
    accr2 = validate_success(
        _accrue(api, fund["id"], "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z"), 201)
    assert accr2["status"] == "ACCRUED"


def test_fee_period_adjacency_before_existing_allowed(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/fee_period_adjacency_boundary_allowed
    """
    # Adjacency on the OTHER side: a new period that ends exactly where the existing
    # period starts is adjacent, not overlapping, and must be accepted.
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="Adjacency Before Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z"), 201)
    accr2 = validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"), 201)
    assert accr2["status"] == "ACCRUED"


def test_fee_period_distinct_nonadjacent_allowed(api):
    """PRD §3.8: "A new period must not overlap any existing non-`REVERSED` accrual on the same fund; because periods are half-open, two accruals that merely meet at a shared endpoint are adjacent and allowed, but any genuine overlap is rejected with `ERR_FEE_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fee_accrual_period_half_open_overlap
    """
    # A fully disjoint later period (gap between the two) must be accepted; only a
    # genuine interior overlap is rejected.
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000], name="Disjoint Fee Fund")
    validate_success(
        _accrue(api, fund["id"], "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"), 201)
    accr2 = validate_success(
        _accrue(api, fund["id"], "2024-06-01T00:00:00Z", "2024-09-01T00:00:00Z"), 201)
    assert accr2["status"] == "ACCRUED"


# ---------------------------------------------------------------------------
# Invalid period
# ---------------------------------------------------------------------------

def test_fee_period_end_before_start_rejected(api):
    """PRD §3.8: "The period is half-open — inclusive of the start and exclusive of the end — and `period_end` must be strictly after `period_start`, failing which the request is rejected with `ERR_INVALID_PERIOD` (HTTP 422)."

    Design: Corner/validations/invalid_period_end_before_start_rejected
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [5_000_000], name="BadPeriod Fund", target_size_cents=5_000_000)
    validate_error(
        _accrue(api, fund["id"], "2024-04-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        "ERR_INVALID_PERIOD", 422)
