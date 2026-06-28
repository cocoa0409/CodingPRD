"""Goal funding: boundary threshold, FUNDED->ACTIVE reopen cycle, insufficient envelope,
target validation.

Translates Difficulty queue (A) non_linear_state_machine (goal), boundary_precision_check
(goal) and Corner queue (B) validations (goals).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_goal_with_funding, setup_household_period_category, contribute,
)


def test_goal_funds_at_exact_target(api):
    """PRD §3.6: "The funding threshold is reached when funded_cents is at least
    target_cents — exactly hitting the target funds the goal, and falling short does not —
    at which point the goal transitions from ACTIVE to FUNDED."

    Design: Difficulty/boundary_precision_check/goal_funds_at_exact_target
    """
    ctx = setup_goal_with_funding(allocated_cents=5000, target_cents=5000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    contribute(hh["id"], goal["id"], owner_headers, 5000)
    data = validate_success(api.get_goal(goal["id"], owner_headers))
    assert data["funded_cents"] == 5000, \
        f"funded == 5000, got {data['funded_cents']}"
    assert data["status"] == "FUNDED", \
        f"funded == target -> FUNDED, got {data['status']}"


def test_goal_falls_short_of_target_stays_active(api):
    """PRD §3.6: "exactly hitting the target funds the goal, and falling short does not".

    Design: Difficulty/boundary_precision_check/goal_funds_at_exact_target
    """
    ctx = setup_goal_with_funding(allocated_cents=5000, target_cents=5000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    contribute(hh["id"], goal["id"], owner_headers, 4999)
    data = validate_success(api.get_goal(goal["id"], owner_headers))
    assert data["funded_cents"] == 4999, \
        f"funded == 4999, got {data['funded_cents']}"
    assert data["status"] == "ACTIVE", \
        f"4999 < 5000 -> still ACTIVE, got {data['status']}"


def test_goal_funded_reopen_cycle_on_target_raise(api):
    """PRD §3.6: "When a goal that had reached FUNDED has its target raised above its
    funded amount, it reopens from FUNDED back to ACTIVE, so the cycle FUNDED → ACTIVE →
    FUNDED is possible as targets are revised upward."

    Design: Difficulty/non_linear_state_machine/goal_funded_reopen_cycle
    """
    ctx = setup_goal_with_funding(allocated_cents=10000, target_cents=5000,
                                  contribution_cents=5000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    assert goal["status"] == "FUNDED", f"setup should leave FUNDED, got {goal['status']}"

    data = validate_success(api.patch_goal(
        hh["id"], goal["id"], {"target_cents": 8000}, owner_headers))
    assert data["status"] == "ACTIVE", \
        f"raise above funded -> ACTIVE, got {data['status']}"
    assert data["funded_cents"] == 5000, \
        f"funded unchanged at 5000, got {data['funded_cents']}"
    assert data["target_cents"] == 8000, \
        f"target raised to 8000, got {data['target_cents']}"


def test_goal_refund_to_new_target_returns_to_funded(api):
    """PRD §3.6: "the cycle FUNDED → ACTIVE → FUNDED is possible as targets are revised
    upward."
    PRD §3.6: "exactly hitting the target funds the goal".

    Design: Difficulty/non_linear_state_machine/goal_funded_reopen_cycle
    """
    ctx = setup_goal_with_funding(allocated_cents=10000, target_cents=5000,
                                  contribution_cents=5000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    # Raise target to 8000 -> ACTIVE.
    reopened = validate_success(api.patch_goal(
        hh["id"], goal["id"], {"target_cents": 8000}, owner_headers))
    assert reopened["status"] == "ACTIVE"
    # Contribute the remaining 3000 -> funded 8000 -> FUNDED again.
    contribute(hh["id"], goal["id"], owner_headers, 3000)
    refunded = validate_success(api.get_goal(goal["id"], owner_headers))
    assert refunded["funded_cents"] == 8000, \
        f"5000 + 3000 = 8000, got {refunded['funded_cents']}"
    assert refunded["status"] == "FUNDED", \
        f"funded == target -> FUNDED, got {refunded['status']}"


def test_contribute_exceeding_envelope_rejected(api):
    """PRD §3.6: "the contribution is rejected if, before the contribution is applied, the
    funding envelope's available_cents is less than the amount_cents requested — the
    envelope must be able to cover it — and that rejection is ERR_INSUFFICIENT_ENVELOPE at
    HTTP 422."

    Design: Corner/validations/contribute_exceeding_envelope_rejected
    """
    ctx = setup_goal_with_funding(allocated_cents=5000, target_cents=20000)
    hh, owner_headers, goal = ctx["household"], ctx["owner_headers"], ctx["goal"]
    resp = api.contribute_goal(
        hh["id"], goal["id"], {"amount_cents": 6000}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ENVELOPE)


def test_goal_target_zero_rejected(api):
    """PRD §3.6: "An owner creates a goal with a name, a target_cents that must be greater
    than zero (otherwise ERR_GOAL_TARGET_BELOW_FUNDED)".

    Design: Corner/validations/goal_target_zero_rejected
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=5000, cat_name="Save", allocated_cents=5000)
    resp = api.create_goal(
        hh["id"],
        {"name": "Bad", "target_cents": 0, "funding_category_id": cat["id"]},
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_GOAL_TARGET_BELOW_FUNDED)
