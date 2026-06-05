"""Available-balance aggregation and the HSA/DCFSA settlement variants, plus the
resettle-of-a-settled-plan-year guard.

Translates Corner/calculations and Corner/state_machines settlement instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    setup_active_hsa, setup_active_fsa, post_contribution,
    settle_plan_year, ApiErrorId,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_available_balance_equals_contributed_minus_reimbursed_for_hsa(api):
    """PRD §3.3: "From these, `available_balance_cents` is `contributed_cents` minus
    `reimbursed_cents` for an HSA".

    After one 250000 HSA contribution and no claims, available_balance_cents == 250000.

    Design: Corner/calculations/available_balance_correct_after_contribution
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    post_contribution(acc["id"], 250000, acc["version"], source="PAYROLL")
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["contributed_cents"] == 250000
    assert after["available_balance_cents"] == 250000


def test_hsa_forfeits_nothing_at_settlement(api):
    """PRD §3.8: "An HSA forfeits nothing and carries nothing — HSA funds roll indefinitely —
    so both its forfeiture and its carryover are zero."
    PRD §3.8: "its `funding_status` moves to `CLOSED` (terminal)".

    An HSA with 100000 unused settles with forfeited_cents 0 and CLOSED.

    Design: Corner/calculations/hsa_no_forfeiture_at_settlement
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    post_contribution(acc["id"], 100000, acc["version"], source="PAYROLL")
    settle_plan_year(py["id"])
    settled = validate_success(api.get_account(acc["id"], ADMIN))
    assert settled["forfeited_cents"] == 0
    assert settled["available_balance_cents"] == 100000
    assert settled["funding_status"] == "CLOSED"


def test_dcfsa_forfeits_entire_unused_at_settlement(api):
    """PRD §3.8: "A DCFSA always forfeits the entire unused balance and may never carry over,
    regardless of relief mode."

    A DCFSA elected 500000 with no claims forfeits the full 500000 and carries nothing.

    Design: Corner/calculations/dcfsa_full_forfeiture_at_settlement
    """
    py, p, acc = setup_active_fsa(
        account_type="DCFSA", elected_amount_cents=500000,
        auto_adjudication_threshold_cents=1000000,
        participant_overrides={"marital_status": "MARRIED_JOINT"})
    settle_plan_year(py["id"])
    settled = validate_success(api.get_account(acc["id"], ADMIN))
    assert settled["forfeited_cents"] == 500000
    rows, _ = validate_paginated(api.list_accounts(
        ADMIN, params={"carryover_source_account_id": acc["id"]}))
    assert rows == [], "DCFSA never carries over"


def test_resettle_settled_plan_year_returns_invalid_state(api):
    """PRD §3.8: "A `PlanAdmin` settles a plan year, which is permitted only while the plan
    year's `lifecycle` is `OPEN`; settling an already-`SETTLED` plan year is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resettle_settled_plan_year_returns_invalid_state
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    settle_plan_year(py["id"])  # advances clock past deadline and settles
    resp = api.settle_plan_year(py["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_plan_year(py["id"], ADMIN))
    assert after["lifecycle"] == "SETTLED"
