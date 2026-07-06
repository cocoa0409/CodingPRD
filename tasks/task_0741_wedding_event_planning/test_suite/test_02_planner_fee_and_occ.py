"""Planner-fee pricing across package tiers, and the contract-creation optimistic
concurrency guard / supersede mechanic.

Covers queue A combinatorial planner-fee (FULL tiered) plus queue B PARTIAL/DAY_OF
fee variants and the two OCC corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    PLANNER,
    create_event,
    create_contract,
    get_event,
)


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: FULL planner fee with budget-tier selection
# ---------------------------------------------------------------------------
def test_full_package_fee_selects_15pct_tier(api):
    """PRD §3.1: "For a `FULL` package, a percentage rate is selected from the
    `total_budget_cents`: if the budget is at most 5,000,000 cents the rate is 12
    percent; if it is greater than 5,000,000 cents but at most 15,000,000 cents the rate
    is 15 percent; if it exceeds 15,000,000 cents the rate is 18 percent."
    PRD §3.1: "The `FULL` fee is then a base of 800,000 cents plus the selected rate
    applied to the entire `total_budget_cents`, with that rate-times-budget product
    rounded half up to whole cents before the base is added."

    Budget 10,000,000 selects the 15% tier: 800,000 + 0.15*10,000,000 = 2,300,000.

    Design: Difficulty/combinatorial_formula/planner_fee_full_budget_tiered
    """
    event = create_event(package_type="FULL", total_budget_cents=10_000_000, guest_count_estimate=150)
    contract = create_contract(event["id"], event["version"])
    assert contract["planner_fee_cents"] == 2_300_000


def test_full_package_fee_copies_package_type(api):
    """PRD §3.1: "A contract copies the event's `package_type` onto itself, is created in
    `DRAFT`, and has its `planner_fee_cents` computed at creation time."
    PRD §3.1: "The `FULL` fee is then a base of 800,000 cents plus the selected rate
    applied to the entire `total_budget_cents`, with that rate-times-budget product
    rounded half up to whole cents before the base is added."

    Design: Difficulty/combinatorial_formula/planner_fee_full_budget_tiered
    """
    event = create_event(package_type="FULL", total_budget_cents=10_000_000, guest_count_estimate=150)
    contract = create_contract(event["id"], event["version"])
    assert contract["package_type"] == "FULL"
    assert contract["planner_fee_cents"] == 2_300_000


# ---------------------------------------------------------------------------
# Queue B — planner fee: PARTIAL and DAY_OF variants
# ---------------------------------------------------------------------------
def test_partial_package_fee_per_guest(api):
    """PRD §3.1: "For a `PARTIAL` package, the fee is a base of 400,000 cents plus 5,000
    cents for every guest in `guest_count_estimate`; this per-guest term is independent
    of the budget."

    400,000 + 5,000*150 = 1,150,000.

    Design: Corner/calculations/planner_fee_partial_per_guest
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=6_000_000, guest_count_estimate=150)
    contract = create_contract(event["id"], event["version"])
    assert contract["planner_fee_cents"] == 1_150_000


def test_dayof_package_fee_flat(api):
    """PRD §3.1: "For a `DAY_OF` package, the fee is a flat 250,000 cents."

    The flat fee is independent of the 20,000,000 budget and 300 guest estimate.

    Design: Corner/calculations/planner_fee_dayof_flat
    """
    event = create_event(package_type="DAY_OF", total_budget_cents=20_000_000, guest_count_estimate=300)
    contract = create_contract(event["id"], event["version"])
    assert contract["planner_fee_cents"] == 250_000


# ---------------------------------------------------------------------------
# Queue B — optimistic concurrency on contract creation
# ---------------------------------------------------------------------------
def test_second_contract_with_stale_version_rejected(api):
    """PRD §2.8: "Before any business processing on this path, the server compares
    `expected_event_version` to the event's current `version`; if the two differ, the
    request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_event_version_on_second_contract_returns_412
    """
    event = create_event(total_budget_cents=8_000_000)
    original_version = event["version"]  # 1
    create_contract(event["id"], original_version)  # bumps the event to version 2
    validate_error(
        api.create_contract(
            {"event_id": event["id"], "expected_event_version": original_version}, PLANNER
        ),
        ApiErrorId.ERR_STALE_EVENT_VERSION.value,
    )


def test_contract_supersede_voids_prior_and_bumps_version(api):
    """PRD §2.8: "A successful contract creation voids the event's prior active
    contract, repoints `active_contract_id` at the new contract, and increments the
    event's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/contract_supersede_voids_prior_and_bumps_version
    """
    event = create_event(total_budget_cents=8_000_000)
    contract_a = create_contract(event["id"], event["version"])  # event -> version 2
    event_v2 = get_event(event["id"])
    contract_b = create_contract(event["id"], event_v2["version"])  # supersede; event -> version 3
    a_after = validate_success(api.get_contract(contract_a["id"], PLANNER))
    assert a_after["status"] == "VOID", "prior active contract must be superseded to VOID"
    event_after = get_event(event["id"])
    assert event_after["active_contract_id"] == contract_b["id"]
    assert event_after["version"] == 3
