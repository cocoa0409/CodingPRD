"""Late-fee computation (four-step nested ladder) and the delinquency timing
boundary.

Covers queue-A combinatorial_formula (late_fee ladder) and boundary_precision_check
(delinquency strict-greater boundary), plus queue-B late-fee corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# combinatorial_formula / late_fee_nested_min_max_ladder
# --------------------------------------------------------------------------- #
def test_late_fee_pct_base_rung_binds(api):
    """PRD §3.10: "First, a percentage base is computed as the balance multiplied
    by the late-fee rate of five percent, rounded up to the next whole cent."
    PRD §3.10: "This evaluation order is fixed — percentage base, then flat floor,
    then absolute cap, then state-law percentage cap — and the order can change
    which limit binds."

    Design: Difficulty/combinatorial_formula/late_fee_nested_min_max_ladder
    """
    bundle = fx.setup_statement_for_late_fee(42501)
    fx.set_clock("2026-07-15T00:00:00Z")
    data = validate_success(api.assess_late_fee(bundle["statement"]["id"], PM))
    # ceil(0.05*42501)=2126, above 500 flat, below 5000 cap, below floor(0.10*42501)=4250
    assert data["late_fee_cents"] == 2126
    assert data["payment_status"] == "DELINQUENT"


def test_late_fee_added_to_statement_totals(api):
    """PRD §3.10: "On assessment the computed late fee is added to the statement,
    the `total_due_cents` and `balance_due_cents` are recomputed, the payment
    status becomes `DELINQUENT`, and the statement's `version` advances."

    Design: Difficulty/combinatorial_formula/late_fee_nested_min_max_ladder
    """
    bundle = fx.setup_statement_for_late_fee(42501)
    before = bundle["statement"]
    fx.set_clock("2026-07-15T00:00:00Z")
    data = validate_success(api.assess_late_fee(before["id"], PM))
    assert data["late_fee_cents"] == 2126
    assert data["total_due_cents"] == before["total_due_cents"] + 2126
    assert data["balance_due_cents"] == before["balance_due_cents"] + 2126
    assert data["version"] == before["version"] + 1


# --------------------------------------------------------------------------- #
# Corner: calculations / late_fee_flat_minimum_binds
# --------------------------------------------------------------------------- #
def test_late_fee_flat_minimum_binds(api):
    """PRD §3.10: "Second, a flat minimum of five hundred cents is applied by
    taking the larger of that flat floor and the percentage base."

    Design: Corner/calculations/late_fee_flat_minimum_binds
    """
    bundle = fx.setup_statement_for_late_fee(8000)
    assert bundle["statement"]["balance_due_cents"] == 8000
    fx.set_clock("2026-07-15T00:00:00Z")
    data = validate_success(api.assess_late_fee(bundle["statement"]["id"], PM))
    # ceil(0.05*8000)=400 < 500 flat; floor(0.10*8000)=800 >= 500 -> flat 500 binds
    assert data["late_fee_cents"] == 500


# --------------------------------------------------------------------------- #
# Corner: calculations / late_fee_state_law_pct_cap_binds_below_flat
# --------------------------------------------------------------------------- #
def test_late_fee_state_law_pct_cap_overrides_flat_floor(api):
    """PRD §3.10: "Fourth, a state-law percentage cap is applied: the fee is
    reduced to the smaller of the running fee and the floor of the balance
    multiplied by the state-law late-fee ceiling of ten percent."

    Design: Corner/calculations/late_fee_state_law_pct_cap_binds_below_flat
    """
    bundle = fx.setup_statement_for_late_fee(3000)
    assert bundle["statement"]["balance_due_cents"] == 3000
    fx.set_clock("2026-07-15T00:00:00Z")
    data = validate_success(api.assess_late_fee(bundle["statement"]["id"], PM))
    # floor(0.10*3000)=300 is below even the 500 flat min -> state-law cap binds
    assert data["late_fee_cents"] == 300


# --------------------------------------------------------------------------- #
# boundary_precision_check / delinquency_strict_greater_than_due_plus_grace_boundary
# --------------------------------------------------------------------------- #
def test_assess_late_fee_at_grace_boundary_rejected(api):
    """PRD §3.10: "Assessment is permitted only when the current clock date is
    strictly past the `due_date` plus the grace window of five days and the
    statement's `balance_due_cents` is still greater than zero; an attempt
    before that grace has elapsed is rejected with `ERR_NOT_YET_DELINQUENT`."

    Design: Difficulty/boundary_precision_check/delinquency_strict_greater_than_due_plus_grace_boundary
    """
    bundle = fx.setup_single_rubs_statement(
        total_cost_cents=20000, state_code="NY", issue_clock="2026-06-15T00:00:00Z"
    )
    # issued 2026-06-15 -> due 2026-07-06 -> due+GRACE(5) = 2026-07-11 boundary day
    fx.set_clock("2026-07-11T00:00:00Z")
    validate_error(
        api.assess_late_fee(bundle["statement"]["id"], PM),
        ApiErrorId.ERR_NOT_YET_DELINQUENT.value,
    )


def test_assess_late_fee_one_day_past_grace_succeeds(api):
    """PRD §3.10: "Assessment may carry an `UNPAID` or `PARTIALLY_PAID`
    statement to `DELINQUENT`."
    PRD §3.10: "Assessment is permitted only when the current clock date is
    strictly past the `due_date` plus the grace window of five days"

    Design: Difficulty/boundary_precision_check/delinquency_strict_greater_than_due_plus_grace_boundary
    """
    bundle = fx.setup_single_rubs_statement(
        total_cost_cents=20000, state_code="NY", issue_clock="2026-06-15T00:00:00Z"
    )
    fx.set_clock("2026-07-12T00:00:00Z")  # one whole day past the 2026-07-11 boundary
    data = validate_success(api.assess_late_fee(bundle["statement"]["id"], PM))
    assert data["payment_status"] == "DELINQUENT"
